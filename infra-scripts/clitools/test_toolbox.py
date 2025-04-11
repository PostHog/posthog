#!/usr/bin/env python3

import unittest
from unittest.mock import patch, MagicMock
import json
import time
from toolbox import parse_arn, sanitize_label, get_current_user, get_toolbox_pod, claim_pod


class TestToolbox(unittest.TestCase):
    def test_sanitize_label(self):
        """Test label sanitization function."""
        # Test basic email sanitization
        self.assertEqual(sanitize_label("user@example.com"), "user_at_example.com")

        # Test with special characters
        self.assertEqual(sanitize_label("user.name@example.com"), "user.name_at_example.com")

        # Test with underscores
        self.assertEqual(sanitize_label("user_name@example.com"), "user_name_at_example.com")

        # Test with leading/trailing underscores
        self.assertEqual(sanitize_label("_user@example.com_"), "user_at_example.com")

    def test_parse_arn_valid(self):
        """Test parsing valid AWS STS ARN."""
        arn = "arn:aws:sts::169684386827:assumed-role/AWSReservedSSO_developers_0847e649a00cc5e7/michael.k@posthog.com"
        expected = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        self.assertEqual(parse_arn(arn), expected)

    def test_parse_arn_different_role(self):
        """Test parsing ARN with different role."""
        arn = "arn:aws:sts::169684386827:assumed-role/AWSReservedSSO_admins_0847e649a00cc5e7/michael.k@posthog.com"
        expected = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "admins", "assumed-role": "true"}
        self.assertEqual(parse_arn(arn), expected)

    def test_parse_arn_unexpected_format(self):
        """Test parsing ARN with unexpected role format."""
        arn = "arn:aws:sts::169684386827:assumed-role/custom-role-name/michael.k@posthog.com"
        expected = {
            "toolbox-claimed": "arn:aws:sts::169684386827:assumed-role/custom-role-name/michael.k_at_posthog.com"
        }
        self.assertEqual(parse_arn(arn), expected)

    @patch("subprocess.run")
    def test_get_current_user(self, mock_run):
        """Test getting current user from kubectl auth."""
        # Mock kubectl auth whoami response
        mock_response = MagicMock()
        mock_response.stdout = json.dumps(
            {
                "status": {
                    "userInfo": {
                        "username": "sso-developers",
                        "extra": {
                            "arn": [
                                "arn:aws:sts::169684386827:assumed-role/AWSReservedSSO_developers_0847e649a00cc5e7/michael.k@posthog.com"
                            ],
                            "sessionName": ["michael.k@posthog.com"],
                        },
                    }
                }
            }
        )
        mock_run.return_value = mock_response

        user_labels = get_current_user()
        expected = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        self.assertEqual(user_labels, expected)
        mock_run.assert_called_once_with(
            ["kubectl", "auth", "whoami", "-o", "json"], capture_output=True, text=True, check=True
        )

    @patch("subprocess.run")
    def test_get_toolbox_pod(self, mock_run):
        """Test getting available toolbox pod."""
        # Mock kubectl get pods response
        mock_response = MagicMock()
        mock_response.stdout = json.dumps(
            {
                "items": [
                    {
                        "metadata": {
                            "name": "toolbox-pod-1",
                            "labels": {
                                "app.kubernetes.io/name": "posthog-toolbox-django",
                                "pod-template-hash": "749c5d8db",
                                "posthog.com/image": "posthog",
                                "posthog.com/team": "infra",
                                "role": "toolbox",
                            },
                            "deletionTimestamp": None,
                        },
                        "status": {"phase": "Running"},
                    }
                ]
            }
        )
        mock_run.return_value = mock_response

        pod_name, is_claimed = get_toolbox_pod("michael.k_at_posthog.com")
        self.assertEqual(pod_name, "toolbox-pod-1")
        self.assertFalse(is_claimed)
        mock_run.assert_called_once_with(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                "posthog",
                "-l",
                "app.kubernetes.io/name=posthog-toolbox-django",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("subprocess.run")
    def test_claim_pod(self, mock_run):
        """Test claiming a pod."""
        # Mock kubectl get pod response
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})

        # Mock kubectl label and annotate responses
        mock_label_response = MagicMock()
        mock_annotate_response = MagicMock()

        # Set up the side effect to handle all kubectl calls
        mock_run.side_effect = [
            mock_get_response,  # get pod labels
            mock_annotate_response,  # add annotation
            mock_label_response,  # add new labels
            mock_label_response,  # wait for pod
        ]

        user_labels = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        claim_pod("toolbox-pod-1", user_labels, 1234567890)

        # Verify kubectl commands were called correctly
        self.assertEqual(mock_run.call_count, 4)

        # Get all calls made to kubectl
        calls = mock_run.call_args_list

        # Verify the first call to get pod labels
        self.assertEqual(
            calls[0][0][0],
            ["kubectl", "get", "pod", "-n", "posthog", "toolbox-pod-1", "-o", "jsonpath={.metadata.labels}"],
        )

        # Verify the annotation call
        self.assertEqual(
            calls[1][0][0],
            [
                "kubectl",
                "annotate",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "karpenter.sh/do-not-disrupt=true",
                "--overwrite=true",
            ],
        )

        # Verify the label call
        self.assertEqual(
            calls[2][0][0],
            [
                "kubectl",
                "label",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "toolbox-claimed=michael.k_at_posthog.com",
                "role-name=developers",
                "assumed-role=true",
                "terminate-after=1234567890",
            ],
        )

        # Verify the wait call
        self.assertEqual(
            calls[3][0][0],
            ["kubectl", "wait", "--for=condition=Ready", "--timeout=5m", "-n", "posthog", "pod", "toolbox-pod-1"],
        )

    @patch("subprocess.run")
    def test_claim_pod_custom_duration(self, mock_run):
        """Test claiming a pod with custom duration."""
        # Mock kubectl get pod response
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps({"app.kubernetes.io/name": "posthog-toolbox-django"})

        # Mock kubectl label and annotate responses
        mock_label_response = MagicMock()
        mock_annotate_response = MagicMock()

        # Set up the side effect to handle all kubectl calls
        mock_run.side_effect = [
            mock_get_response,  # get pod labels
            mock_annotate_response,  # add annotation
            mock_label_response,  # add new labels
            mock_label_response,  # wait for pod
        ]

        # Calculate timestamp 4 hours from now
        future_timestamp = int(time.time()) + (4 * 60 * 60)

        user_labels = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        claim_pod("toolbox-pod-1", user_labels, future_timestamp)

        # Verify kubectl commands were called correctly
        self.assertEqual(mock_run.call_count, 4)

        # Get all calls made to kubectl
        calls = mock_run.call_args_list

        # Verify the label call includes the future timestamp
        self.assertEqual(
            calls[2][0][0],
            [
                "kubectl",
                "label",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "toolbox-claimed=michael.k_at_posthog.com",
                "role-name=developers",
                "assumed-role=true",
                f"terminate-after={future_timestamp}",
            ],
        )

    @patch("subprocess.run")
    def test_update_claim(self, mock_run):
        """Test updating an existing pod claim."""
        # Mock kubectl get pod response
        mock_get_response = MagicMock()
        mock_get_response.stdout = json.dumps(
            {
                "app.kubernetes.io/name": "posthog-toolbox-django",
                "toolbox-claimed": "michael.k_at_posthog.com",
                "role-name": "developers",
                "assumed-role": "true",
                "terminate-after": "1234567890",
            }
        )

        # Mock kubectl label and annotate responses
        mock_label_response = MagicMock()
        mock_annotate_response = MagicMock()

        # Set up the side effect to handle all kubectl calls
        mock_run.side_effect = [
            mock_get_response,  # get pod labels
            mock_label_response,  # remove toolbox-claimed
            mock_label_response,  # remove role-name
            mock_label_response,  # remove assumed-role
            mock_label_response,  # remove terminate-after
            mock_annotate_response,  # add annotation
            mock_label_response,  # add new labels
            mock_label_response,  # wait for pod
        ]

        # Calculate new timestamp 24 hours from now
        future_timestamp = int(time.time()) + (24 * 60 * 60)

        user_labels = {"toolbox-claimed": "michael.k_at_posthog.com", "role-name": "developers", "assumed-role": "true"}
        claim_pod("toolbox-pod-1", user_labels, future_timestamp)

        # Verify kubectl commands were called correctly
        self.assertEqual(mock_run.call_count, 8)

        # Get all calls made to kubectl
        calls = mock_run.call_args_list

        # Verify the first call to get pod labels
        self.assertEqual(
            calls[0][0][0],
            ["kubectl", "get", "pod", "-n", "posthog", "toolbox-pod-1", "-o", "jsonpath={.metadata.labels}"],
        )

        # Verify the label removal calls
        self.assertEqual(
            calls[1][0][0], ["kubectl", "label", "pod", "-n", "posthog", "toolbox-pod-1", "toolbox-claimed-"]
        )
        self.assertEqual(calls[2][0][0], ["kubectl", "label", "pod", "-n", "posthog", "toolbox-pod-1", "role-name-"])
        self.assertEqual(calls[3][0][0], ["kubectl", "label", "pod", "-n", "posthog", "toolbox-pod-1", "assumed-role-"])
        self.assertEqual(
            calls[4][0][0], ["kubectl", "label", "pod", "-n", "posthog", "toolbox-pod-1", "terminate-after-"]
        )

        # Verify the annotation call
        self.assertEqual(
            calls[5][0][0],
            [
                "kubectl",
                "annotate",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "karpenter.sh/do-not-disrupt=true",
                "--overwrite=true",
            ],
        )

        # Verify the label call
        self.assertEqual(
            calls[6][0][0],
            [
                "kubectl",
                "label",
                "pod",
                "-n",
                "posthog",
                "toolbox-pod-1",
                "toolbox-claimed=michael.k_at_posthog.com",
                "role-name=developers",
                "assumed-role=true",
                f"terminate-after={future_timestamp}",
            ],
        )

        # Verify the wait call
        self.assertEqual(
            calls[7][0][0],
            ["kubectl", "wait", "--for=condition=Ready", "--timeout=5m", "-n", "posthog", "pod", "toolbox-pod-1"],
        )


if __name__ == "__main__":
    unittest.main()
