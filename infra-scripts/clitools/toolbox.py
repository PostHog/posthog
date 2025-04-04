#!/usr/bin/env python3

import subprocess
import json
from datetime import datetime, timedelta
import sys
import argparse
import time


def get_current_user() -> dict:
    """Get user identity from kubectl auth and parse it into labels."""
    try:
        print("Attempting to get user identity...")  # noqa: T201
        whoami = subprocess.run(["kubectl", "auth", "whoami", "-o", "json"], capture_output=True, text=True, check=True)

        user_info = json.loads(whoami.stdout)
        user_info = user_info["status"]["userInfo"]  # Navigate to the correct nesting level

        # First try to get the ARN from the extra info
        if "extra" in user_info and "arn" in user_info["extra"]:
            return parse_arn(user_info["extra"]["arn"][0])  # The ARN is in a list

        # Fallback to sessionName if available
        if "extra" in user_info and "sessionName" in user_info["extra"]:
            return {"toolbox-claimed": sanitize_label(user_info["extra"]["sessionName"][0])}

        # Final fallback to username
        return {"toolbox-claimed": sanitize_label(f"k8s-user/{user_info['username']}")}

    except subprocess.CalledProcessError as e:
        print(f"Command failed with return code {e.returncode}")  # noqa: T201
        print(f"Output: {e.output}")  # noqa: T201
        print(f"Stderr: {e.stderr}")  # noqa: T201
        sys.exit(1)
    except Exception as k8s_error:
        print(f"Error: Failed to get user identity: {k8s_error}")  # noqa: T201
        print(f"Error type: {type(k8s_error)}")  # noqa: T201
        sys.exit(1)


def get_toolbox_pod(user: str, check_claimed: bool = True) -> tuple[str, bool]:
    """Get an available toolbox pod name.

    Args:
        user: Current user ARN
        check_claimed: If True, first look for pods already claimed by the user

    Returns:
        Tuple of (pod_name, is_already_claimed)
    """
    wait_start = datetime.now()
    max_wait = timedelta(minutes=5)
    update_interval = timedelta(seconds=30)
    next_update = wait_start

    while True:
        try:
            result = subprocess.run(
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
            pods = json.loads(result.stdout)["items"]

            if check_claimed:
                # Get user ID from ARN and sanitize it
                user_id = sanitize_label(user.split("/")[-1] if "/" in user else user)
                # First look for pods already claimed by this user
                claimed_pods = [
                    pod["metadata"]["name"]
                    for pod in pods
                    if pod["status"]["phase"] == "Running"
                    and pod.get("metadata", {}).get("labels", {}).get("toolbox-claimed") == user_id
                    and not pod.get("metadata", {}).get("deletionTimestamp")
                ]

                if claimed_pods:
                    print("⚠️  Found pod already claimed by you")  # noqa: T201
                    return claimed_pods[0], True
                print("No pods currently claimed by you, looking for available pods...")  # noqa: T201

            # Look for unclaimed pods
            available_pods = [
                pod["metadata"]["name"]
                for pod in pods
                if pod["status"]["phase"] in ("Running", "Pending")
                and "toolbox-claimed" not in pod.get("metadata", {}).get("labels", {})
                and "terminate-after" not in pod.get("metadata", {}).get("labels", {})
                and not pod.get("metadata", {}).get("deletionTimestamp")
            ]

            if available_pods:
                return available_pods[0], False

            # No pods available, check if we should wait or timeout
            current_time = datetime.now()
            if current_time - wait_start > max_wait:
                print("\n❌ No pods became available after 5 minutes.")  # noqa: T201
                print("Please reach out to #team-infrastructure for assistance.")  # noqa: T201
                sys.exit(1)

            # Check if we should print an update
            if current_time >= next_update:
                wait_time = current_time - wait_start
                print(f"⏳ Waiting for available pod... ({int(wait_time.total_seconds())}s)")  # noqa: T201
                next_update = current_time + update_interval

            # Wait before next check
            time.sleep(2)

        except Exception as e:
            print(f"Error getting toolbox pod: {e}")  # noqa: T201
            sys.exit(1)


def parse_arn(arn: str) -> dict:
    """Parse AWS ARN into components."""
    try:
        # Handle AWS STS assumed-role ARN format
        # Format: arn:aws:sts::ACCOUNT:assumed-role/AWSReservedSSO_developers_0847e649a00cc5e7/michael.k@posthog.com
        parts = arn.split(":")
        if len(parts) != 6 or "assumed-role" not in parts[5]:
            return {"toolbox-claimed": sanitize_label(arn)}  # fallback for unexpected format

        # Extract role path and session name
        role_and_session = parts[5].split("/")
        if len(role_and_session) < 3:
            return {"toolbox-claimed": sanitize_label(arn)}

        role_path = role_and_session[1]  # The full role path (e.g. AWSReservedSSO_developers_0847e649a00cc5e7)
        session_name = role_and_session[2]  # The session name (email)

        # Extract role name from the role path (e.g. "developers" from "AWSReservedSSO_developers_0847e649a00cc5e7")
        role_parts = role_path.split("_")
        role_name = role_parts[1]  # For AWSReservedSSO_* format

        # Sanitize values for kubernetes labels
        session_name = sanitize_label(session_name)
        role_name = sanitize_label(role_name)

        print(f"Parsed ARN: session_name={session_name}, role_name={role_name}")  # noqa: T201

        return {
            "toolbox-claimed": session_name,  # The sanitized email address
            "role-name": role_name,  # The role name (e.g. "developers")
            "assumed-role": "true",
        }
    except Exception as e:
        print(f"Warning: Failed to parse ARN ({e}), using fallback format")  # noqa: T201
        return {"toolbox-claimed": sanitize_label(arn)}  # fallback for any parsing errors


def sanitize_label(value: str) -> str:
    """Sanitize a value to be a valid kubernetes label value."""
    # Replace @ with _at_ and keep dots
    sanitized = value.replace("@", "_at_")
    # Ensure it starts and ends with alphanumeric
    sanitized = sanitized.strip("_")
    return sanitized


def claim_pod(pod_name: str, user_labels: dict, timestamp: int):
    """Claim the pod by updating its labels."""

    human_readable = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"Claiming pod {pod_name} for user {user_labels.get('toolbox-claimed', 'unknown')} until {human_readable}")  # noqa: T201
    try:
        # Get current labels
        result = subprocess.run(
            ["kubectl", "get", "pod", "-n", "posthog", pod_name, "-o", "jsonpath={.metadata.labels}"],
            capture_output=True,
            text=True,
            check=True,
        )

        current_labels = json.loads(result.stdout)

        # Remove all labels except app.kubernetes.io/name
        for label_name in current_labels.keys():
            if label_name != "app.kubernetes.io/name":
                subprocess.run(
                    ["kubectl", "label", "pod", "-n", "posthog", pod_name, f"{label_name}-"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        # Add karpenter.sh/do-not-disrupt annotation
        subprocess.run(
            [
                "kubectl",
                "annotate",
                "pod",
                "-n",
                "posthog",
                pod_name,
                "karpenter.sh/do-not-disrupt=true",
                "--overwrite=true",
            ],
            check=True,
        )

        # Build label arguments
        label_args = [f"{key}={value}" for key, value in {**user_labels, "terminate-after": str(timestamp)}.items()]

        # Add new labels
        subprocess.run(["kubectl", "label", "pod", "-n", "posthog", pod_name, *label_args], check=True)

        # Wait for pod to be ready
        print("⏳ Waiting for pod to be ready")  # noqa: T201
        subprocess.run(["kubectl", "wait", "--for=condition=Ready", "--timeout=5m", "-n", "posthog", "pod", pod_name])
    except Exception as e:
        print(f"Error claiming pod: {e}")  # noqa: T201
        sys.exit(1)


def delete_pod(pod_name: str):
    """Delete the specified pod.

    Args:
        pod_name: Name of the pod to delete
    """
    response = input("\n❓ Would you like to delete this pod now? [y/N]: ").lower().strip()
    if response == "y":
        print("🗑️  Deleting pod...")  # noqa: T201
        try:
            subprocess.run(
                [
                    "kubectl",
                    "delete",
                    "pod",
                    "-n",
                    "posthog",
                    pod_name,
                    "--wait=false",  # Don't wait for pod deletion to complete
                ],
                check=True,
            )
            print("✅ Pod scheduled for deletion")  # noqa: T201
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to delete pod: {e}")  # noqa: T201
    else:
        print("👋 Pod will remain running until its scheduled termination time")  # noqa: T201


def connect_to_pod(pod_name: str):
    """Connect to the specified pod using kubectl exec.

    Args:
        pod_name: Name of the pod to connect to
    """
    print(f"🚀 Connecting to pod {pod_name}...")  # noqa: T201
    subprocess.run(["kubectl", "exec", "-it", "-n", "posthog", pod_name, "--", "bash"])


def main():
    try:
        # Set up argument parser
        parser = argparse.ArgumentParser(
            description="Connect to a toolbox pod and manage pod claims. This script will automatically connect you to your latest claimed pod.",
            epilog="Example: toolbox.py --claim-duration 24  # Claims a pod for 24 hours",
        )
        parser.add_argument(
            "--claim-duration",
            type=float,
            default=12,
            help="Duration in hours to claim the pod for (default: 12). The pod will be automatically terminated after this duration.",
        )
        parser.add_argument(
            "--update-claim",
            action="store_true",
            help="Update the termination time of your existing claimed pod instead of claiming a new one.",
        )
        args = parser.parse_args()

        print("🛠️  Connecting to toolbox pod...")  # noqa: T201

        # Get current user labels
        user_labels = get_current_user()
        print(f"👤 Current user labels: {user_labels}")  # noqa: T201

        # Get available pod
        pod_name, is_already_claimed = get_toolbox_pod(user_labels["toolbox-claimed"], check_claimed=True)
        print(f"🎯 Found pod: {pod_name}")  # noqa: T201

        # Calculate duration
        future_time = datetime.now() + timedelta(hours=args.claim_duration)
        timestamp = int(future_time.timestamp())
        human_readable = future_time.strftime("%Y-%m-%d %H:%M:%S")

        # Claim or update pod
        if not is_already_claimed or args.update_claim:
            print(f"⏰ {'Updating' if is_already_claimed else 'Setting'} pod termination time to: {human_readable}")  # noqa: T201
            claim_pod(pod_name, user_labels, timestamp)
            print(f"✅ Successfully {'updated' if is_already_claimed else 'claimed'} pod: {pod_name}")  # noqa: T201
        else:
            print("✅ Connecting to your existing pod (use --update-claim to extend the duration)")  # noqa: T201

        try:
            connect_to_pod(pod_name)
        finally:
            delete_pod(pod_name)
    except KeyboardInterrupt:
        print("\n👋 Goodbye! \n \n Did something not work as expected? Ask in #team-infrastructure")  # noqa: T201
        sys.exit(0)


if __name__ == "__main__":
    main()
