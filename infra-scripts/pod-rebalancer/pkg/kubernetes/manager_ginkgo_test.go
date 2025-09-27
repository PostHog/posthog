package kubernetes

import (
	"context"
	"errors"
	"fmt"
	"time"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	v1 "k8s.io/api/core/v1"
	kerrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
	ktesting "k8s.io/client-go/testing"

	"github.com/posthog/pod-rebalancer/pkg/logging"
)

var _ = Describe("PodManager", func() {
	var (
		manager   *PodManager
		client    *fake.Clientset
		logger    *logging.Logger
		namespace string
		ctx       context.Context
	)

	BeforeEach(func() {
		client = fake.NewSimpleClientset()
		logger, _ = logging.New("error") // Use error level to minimize test output
		namespace = "posthog"
		ctx = context.Background()
	})

	Describe("NewManagerWithClient", func() {
		It("should create a PodManager with provided client", func() {
			manager = NewManagerWithClient(client, namespace, false, logger)

			Expect(manager).NotTo(BeNil())
			Expect(manager.namespace).To(Equal(namespace))
			Expect(manager.dryRun).To(BeFalse())
			Expect(manager.logger).To(Equal(logger))
		})
	})

	Describe("DeletePods", func() {
		BeforeEach(func() {
			manager = NewManagerWithClient(client, namespace, false, logger)
		})

		Context("with no pods to delete", func() {
			It("should return empty result", func() {
				result, err := manager.DeletePods(ctx, []string{})

				Expect(err).NotTo(HaveOccurred())
				Expect(result.Attempted).To(BeEmpty())
				Expect(result.Deleted).To(BeEmpty())
				Expect(result.Skipped).To(BeEmpty())
				Expect(result.Errors).To(BeEmpty())
			})
		})

		Context("with running pods", func() {
			BeforeEach(func() {
				// Create test pods
				pod1 := &v1.Pod{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-1",
						Namespace: namespace,
					},
					Status: v1.PodStatus{
						Phase: v1.PodRunning,
					},
					Spec: v1.PodSpec{
						NodeName: "node-1",
					},
				}
				pod2 := &v1.Pod{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod-2",
						Namespace: namespace,
					},
					Status: v1.PodStatus{
						Phase: v1.PodRunning,
					},
					Spec: v1.PodSpec{
						NodeName: "node-2",
					},
				}

				client.CoreV1().Pods(namespace).Create(ctx, pod1, metav1.CreateOptions{})
				client.CoreV1().Pods(namespace).Create(ctx, pod2, metav1.CreateOptions{})
			})

			Context("in production mode", func() {
				BeforeEach(func() {
					manager = NewManagerWithClient(client, namespace, false, logger)
				})

				It("should delete pods successfully", func() {
					podNames := []string{"test-pod-1", "test-pod-2"}
					result, err := manager.DeletePods(ctx, podNames)

					Expect(err).NotTo(HaveOccurred())
					Expect(result.Attempted).To(Equal(podNames))
					Expect(result.Deleted).To(Equal(podNames))
					Expect(result.Skipped).To(BeEmpty())
					Expect(result.Errors).To(BeEmpty())

					// Verify pods were actually deleted
					actions := client.Actions()
					deleteActions := 0
					for _, action := range actions {
						if action.GetVerb() == "delete" && action.GetResource().Resource == "pods" {
							deleteActions++
						}
					}
					Expect(deleteActions).To(Equal(2))
				})
			})

			Context("in dry-run mode", func() {
				BeforeEach(func() {
					manager = NewManagerWithClient(client, namespace, true, logger)
				})

				It("should simulate pod deletion without actually deleting", func() {
					podNames := []string{"test-pod-1", "test-pod-2"}
					result, err := manager.DeletePods(ctx, podNames)

					Expect(err).NotTo(HaveOccurred())
					Expect(result.Attempted).To(Equal(podNames))
					Expect(result.Deleted).To(Equal(podNames))
					Expect(result.Skipped).To(BeEmpty())
					Expect(result.Errors).To(BeEmpty())

					// Verify no actual delete actions were performed
					actions := client.Actions()
					deleteActions := 0
					for _, action := range actions {
						if action.GetVerb() == "delete" && action.GetResource().Resource == "pods" {
							deleteActions++
						}
					}
					Expect(deleteActions).To(Equal(0))
				})
			})
		})

		Context("with pods already being deleted", func() {
			BeforeEach(func() {
				manager = NewManagerWithClient(client, namespace, false, logger)

				// Create a pod with deletion timestamp
				deletionTime := metav1.NewTime(time.Now())
				pod := &v1.Pod{
					ObjectMeta: metav1.ObjectMeta{
						Name:              "deleting-pod",
						Namespace:         namespace,
						DeletionTimestamp: &deletionTime,
					},
					Status: v1.PodStatus{
						Phase: v1.PodRunning,
					},
				}

				client.CoreV1().Pods(namespace).Create(ctx, pod, metav1.CreateOptions{})
			})

			It("should skip pods already being deleted", func() {
				result, err := manager.DeletePods(ctx, []string{"deleting-pod"})

				Expect(err).NotTo(HaveOccurred())
				Expect(result.Attempted).To(Equal([]string{"deleting-pod"}))
				Expect(result.Deleted).To(BeEmpty())
				Expect(result.Skipped).To(HaveKeyWithValue("deleting-pod", "already being deleted"))
				Expect(result.Errors).To(BeEmpty())
			})
		})

		Context("with pods in terminal states", func() {
			BeforeEach(func() {
				manager = NewManagerWithClient(client, namespace, false, logger)

				// Create pods in terminal states
				succeededPod := &v1.Pod{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "succeeded-pod",
						Namespace: namespace,
					},
					Status: v1.PodStatus{
						Phase: v1.PodSucceeded,
					},
				}
				failedPod := &v1.Pod{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "failed-pod",
						Namespace: namespace,
					},
					Status: v1.PodStatus{
						Phase: v1.PodFailed,
					},
				}

				client.CoreV1().Pods(namespace).Create(ctx, succeededPod, metav1.CreateOptions{})
				client.CoreV1().Pods(namespace).Create(ctx, failedPod, metav1.CreateOptions{})
			})

			It("should skip pods in terminal states", func() {
				podNames := []string{"succeeded-pod", "failed-pod"}
				result, err := manager.DeletePods(ctx, podNames)

				Expect(err).NotTo(HaveOccurred())
				Expect(result.Attempted).To(Equal(podNames))
				Expect(result.Deleted).To(BeEmpty())
				Expect(result.Skipped).To(HaveKeyWithValue("succeeded-pod", "pod in Succeeded state"))
				Expect(result.Skipped).To(HaveKeyWithValue("failed-pod", "pod in Failed state"))
				Expect(result.Errors).To(BeEmpty())
			})
		})

		Context("with non-existent pods", func() {
			BeforeEach(func() {
				manager = NewManagerWithClient(client, namespace, false, logger)
			})

			It("should return error for non-existent pods", func() {
				result, err := manager.DeletePods(ctx, []string{"non-existent-pod"})

				Expect(err).NotTo(HaveOccurred())
				Expect(result.Attempted).To(Equal([]string{"non-existent-pod"}))
				Expect(result.Deleted).To(BeEmpty())
				Expect(result.Skipped).To(BeEmpty())
				Expect(result.Errors).To(HaveKey("non-existent-pod"))
				Expect(result.Errors["non-existent-pod"]).To(MatchError(ContainSubstring("failed to get pod")))
			})
		})

		Context("with deletion errors", func() {
			BeforeEach(func() {
				manager = NewManagerWithClient(client, namespace, false, logger)

				// Create a pod
				pod := &v1.Pod{
					ObjectMeta: metav1.ObjectMeta{
						Name:      "test-pod",
						Namespace: namespace,
					},
					Status: v1.PodStatus{
						Phase: v1.PodRunning,
					},
				}
				client.CoreV1().Pods(namespace).Create(ctx, pod, metav1.CreateOptions{})

				// Set up client to return error on delete
				client.PrependReactor("delete", "pods", func(action ktesting.Action) (handled bool, ret runtime.Object, err error) {
					return true, nil, errors.New("simulated delete error")
				})
			})

			It("should handle deletion errors gracefully", func() {
				result, err := manager.DeletePods(ctx, []string{"test-pod"})

				Expect(err).NotTo(HaveOccurred())
				Expect(result.Attempted).To(Equal([]string{"test-pod"}))
				Expect(result.Deleted).To(BeEmpty())
				Expect(result.Skipped).To(BeEmpty())
				Expect(result.Errors).To(HaveKey("test-pod"))
				Expect(result.Errors["test-pod"]).To(MatchError(ContainSubstring("failed to delete pod")))
			})
		})
	})

	Describe("ValidateMinimumPods", func() {
		BeforeEach(func() {
			manager = NewManagerWithClient(client, namespace, false, logger)
		})

		Context("with sufficient pods after deletion", func() {
			BeforeEach(func() {
				// Create 5 running pods
				for i := 1; i <= 5; i++ {
					pod := &v1.Pod{
						ObjectMeta: metav1.ObjectMeta{
							Name:      fmt.Sprintf("pod-%d", i),
							Namespace: namespace,
							Labels: map[string]string{
								"app": "test-app",
							},
						},
						Status: v1.PodStatus{
							Phase: v1.PodRunning,
						},
					}
					client.CoreV1().Pods(namespace).Create(ctx, pod, metav1.CreateOptions{})
				}
			})

			It("should pass validation when minimum pods requirement is met", func() {
				podsToDelete := []string{"pod-1", "pod-2"}
				err := manager.ValidateMinimumPods(ctx, podsToDelete, "app=test-app", 3)

				Expect(err).NotTo(HaveOccurred())
			})
		})

		Context("with insufficient pods after deletion", func() {
			BeforeEach(func() {
				// Create only 3 running pods
				for i := 1; i <= 3; i++ {
					pod := &v1.Pod{
						ObjectMeta: metav1.ObjectMeta{
							Name:      fmt.Sprintf("pod-%d", i),
							Namespace: namespace,
							Labels: map[string]string{
								"app": "test-app",
							},
						},
						Status: v1.PodStatus{
							Phase: v1.PodRunning,
						},
					}
					client.CoreV1().Pods(namespace).Create(ctx, pod, metav1.CreateOptions{})
				}
			})

			It("should fail validation when minimum pods requirement is not met", func() {
				podsToDelete := []string{"pod-1", "pod-2"}
				err := manager.ValidateMinimumPods(ctx, podsToDelete, "app=test-app", 3)

				Expect(err).To(HaveOccurred())
				Expect(err.Error()).To(ContainSubstring("deletion would leave 1 pods, minimum required is 3"))
			})
		})

		Context("with pods already being deleted", func() {
			BeforeEach(func() {
				// Create 3 running pods
				for i := 1; i <= 3; i++ {
					pod := &v1.Pod{
						ObjectMeta: metav1.ObjectMeta{
							Name:      fmt.Sprintf("pod-%d", i),
							Namespace: namespace,
							Labels: map[string]string{
								"app": "test-app",
							},
						},
						Status: v1.PodStatus{
							Phase: v1.PodRunning,
						},
					}
					client.CoreV1().Pods(namespace).Create(ctx, pod, metav1.CreateOptions{})
				}

				// Create one pod already being deleted (should not count in validation)
				deletionTime := metav1.NewTime(time.Now())
				deletingPod := &v1.Pod{
					ObjectMeta: metav1.ObjectMeta{
						Name:              "deleting-pod",
						Namespace:         namespace,
						DeletionTimestamp: &deletionTime,
						Labels: map[string]string{
							"app": "test-app",
						},
					},
					Status: v1.PodStatus{
						Phase: v1.PodRunning,
					},
				}
				client.CoreV1().Pods(namespace).Create(ctx, deletingPod, metav1.CreateOptions{})
			})

			It("should not count pods already being deleted", func() {
				podsToDelete := []string{"pod-1"}
				err := manager.ValidateMinimumPods(ctx, podsToDelete, "app=test-app", 2)

				Expect(err).NotTo(HaveOccurred())
			})
		})

		Context("with list pods error", func() {
			BeforeEach(func() {
				manager = NewManagerWithClient(client, namespace, false, logger)

				// Set up client to return error on list
				client.PrependReactor("list", "pods", func(action ktesting.Action) (handled bool, ret runtime.Object, err error) {
					return true, nil, kerrors.NewInternalError(errors.New("simulated list error"))
				})
			})

			It("should return error when listing pods fails", func() {
				podsToDelete := []string{"pod-1"}
				err := manager.ValidateMinimumPods(ctx, podsToDelete, "app=test-app", 2)

				Expect(err).To(HaveOccurred())
				Expect(err.Error()).To(ContainSubstring("failed to list pods for validation"))
			})
		})
	})
})
