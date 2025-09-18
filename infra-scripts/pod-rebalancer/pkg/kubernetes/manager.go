package kubernetes

import (
	"context"
	"fmt"

	"go.uber.org/zap"
	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"

	"github.com/posthog/pod-rebalancer/pkg/logging"
)

// PodManager handles Kubernetes pod operations with dry-run support
type PodManager struct {
	client    kubernetes.Interface
	namespace string
	dryRun    bool
	logger    *logging.Logger
}

// DeletionResult tracks what happened during pod deletions
type DeletionResult struct {
	Attempted []string          // Pod names that were attempted to be deleted
	Deleted   []string          // Pod names that were successfully deleted
	Skipped   map[string]string // pod name -> skip reason
	Errors    map[string]error  // pod name -> error
}

// NewManager creates a new PodManager with the provided configuration
func NewManager(namespace string, dryRun bool, logger *logging.Logger) (*PodManager, error) {
	client, err := createKubernetesClient()
	if err != nil {
		return nil, fmt.Errorf("failed to create kubernetes client: %w", err)
	}

	return &PodManager{
		client:    client,
		namespace: namespace,
		dryRun:    dryRun,
		logger:    logger,
	}, nil
}

// NewManagerWithClient creates a PodManager with a provided client (useful for testing)
func NewManagerWithClient(client kubernetes.Interface, namespace string, dryRun bool, logger *logging.Logger) *PodManager {
	return &PodManager{
		client:    client,
		namespace: namespace,
		dryRun:    dryRun,
		logger:    logger,
	}
}

// DeletePods deletes the specified pods, respecting dry-run mode
func (pm *PodManager) DeletePods(ctx context.Context, podNames []string) (*DeletionResult, error) {
	result := &DeletionResult{
		Attempted: make([]string, 0, len(podNames)),
		Deleted:   make([]string, 0, len(podNames)),
		Skipped:   make(map[string]string),
		Errors:    make(map[string]error),
	}

	if len(podNames) == 0 {
		pm.logger.Info("No pods to delete")
		return result, nil
	}

	pm.logger.Info("Starting pod deletion process",
		zap.Strings("pod_names", podNames),
		zap.Bool("dry_run", pm.dryRun),
		zap.String("namespace", pm.namespace))

	for _, podName := range podNames {
		result.Attempted = append(result.Attempted, podName)

		if err := pm.deleteSinglePod(ctx, podName, result); err != nil {
			pm.logger.Error("Failed to delete pod",
				zap.String("pod_name", podName),
				zap.Error(err))
			result.Errors[podName] = err
		}
	}

	pm.logger.Info("Pod deletion process completed",
		zap.Int("attempted", len(result.Attempted)),
		zap.Int("deleted", len(result.Deleted)),
		zap.Int("skipped", len(result.Skipped)),
		zap.Int("errors", len(result.Errors)))

	return result, nil
}

// deleteSinglePod handles the deletion of a single pod
func (pm *PodManager) deleteSinglePod(ctx context.Context, podName string, result *DeletionResult) error {
	// First, verify the pod exists and get its current state
	pod, err := pm.client.CoreV1().Pods(pm.namespace).Get(ctx, podName, metav1.GetOptions{})
	if err != nil {
		return fmt.Errorf("failed to get pod %s: %w", podName, err)
	}

	// Check if pod is already being deleted
	if pod.DeletionTimestamp != nil {
		pm.logger.Info("Pod already being deleted, skipping",
			zap.String("pod_name", podName))
		result.Skipped[podName] = "already being deleted"
		return nil
	}

	// Check if pod is in a state that should not be deleted
	if pod.Status.Phase == v1.PodSucceeded || pod.Status.Phase == v1.PodFailed {
		pm.logger.Info("Pod in terminal state, skipping",
			zap.String("pod_name", podName),
			zap.String("phase", string(pod.Status.Phase)))
		result.Skipped[podName] = fmt.Sprintf("pod in %s state", pod.Status.Phase)
		return nil
	}

	if pm.dryRun {
		pm.logger.Info("DRY RUN: Would delete pod",
			zap.String("pod_name", podName),
			zap.String("phase", string(pod.Status.Phase)),
			zap.String("node", pod.Spec.NodeName))
		result.Deleted = append(result.Deleted, podName)
		return nil
	}

	// Perform actual deletion
	deleteOptions := metav1.DeleteOptions{
		GracePeriodSeconds: &[]int64{30}[0], // 30 second grace period
	}

	err = pm.client.CoreV1().Pods(pm.namespace).Delete(ctx, podName, deleteOptions)
	if err != nil {
		return fmt.Errorf("failed to delete pod %s: %w", podName, err)
	}

	pm.logger.Info("Successfully deleted pod",
		zap.String("pod_name", podName),
		zap.String("namespace", pm.namespace))
	result.Deleted = append(result.Deleted, podName)

	return nil
}

// ValidateMinimumPods checks if deleting the specified pods would leave fewer than minimum required pods
func (pm *PodManager) ValidateMinimumPods(ctx context.Context, podsToDelete []string, labelSelector string, minimumPods int) error {
	// Get current pods matching the selector
	listOptions := metav1.ListOptions{}
	if labelSelector != "" {
		listOptions.LabelSelector = labelSelector
	}

	podList, err := pm.client.CoreV1().Pods(pm.namespace).List(ctx, listOptions)
	if err != nil {
		return fmt.Errorf("failed to list pods for validation: %w", err)
	}

	// Count running pods (exclude those already being deleted)
	runningPods := 0
	for _, pod := range podList.Items {
		if pod.DeletionTimestamp == nil && pod.Status.Phase == v1.PodRunning {
			runningPods++
		}
	}

	podsAfterDeletion := runningPods - len(podsToDelete)
	if podsAfterDeletion < minimumPods {
		return fmt.Errorf("deletion would leave %d pods, minimum required is %d", podsAfterDeletion, minimumPods)
	}

	pm.logger.Info("Minimum pod validation passed",
		zap.Int("current_running_pods", runningPods),
		zap.Int("pods_to_delete", len(podsToDelete)),
		zap.Int("pods_after_deletion", podsAfterDeletion),
		zap.Int("minimum_required", minimumPods))

	return nil
}

// createKubernetesClient creates a Kubernetes client using in-cluster config or kubeconfig
func createKubernetesClient() (kubernetes.Interface, error) {
	// Try in-cluster configuration first (when running in a pod)
	config, err := rest.InClusterConfig()
	if err != nil {
		// Fallback to kubeconfig (for local development)
		config, err = clientcmd.BuildConfigFromFlags("", clientcmd.RecommendedHomeFile)
		if err != nil {
			return nil, fmt.Errorf("failed to build kubernetes config: %w", err)
		}
	}

	client, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, fmt.Errorf("failed to create kubernetes client: %w", err)
	}

	return client, nil
}
