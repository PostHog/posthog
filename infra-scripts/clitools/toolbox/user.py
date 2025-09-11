#!/usr/bin/env python3
"""User identification and pod claiming functions."""

import re
import sys
import json
import subprocess


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
        if len(role_parts) < 2:
            return {"toolbox-claimed": sanitize_label(arn)}  # fallback for unexpected format
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
    """Sanitize a value to be a valid kubernetes label value (RFC 1123)."""
    # Replace @ with _at_ and keep dots
    sanitized = value.replace("@", "_at_")
    # Only allow alphanumeric, '-', '_', '.'
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", sanitized)
    # Must start and end with alphanumeric
    sanitized = re.sub(r"^[^A-Za-z0-9]+", "", sanitized)
    sanitized = re.sub(r"[^A-Za-z0-9]+$", "", sanitized)

    # If longer than 63 chars, keep the start and end parts
    if len(sanitized) > 63:
        # Keep first 31 chars and last 31 chars with a single underscore in between
        sanitized = sanitized[:31] + "_" + sanitized[-31:]

    # If after truncation it ends or starts with non-alphanumeric, strip again
    sanitized = re.sub(r"^[^A-Za-z0-9]+", "", sanitized)
    sanitized = re.sub(r"[^A-Za-z0-9]+$", "", sanitized)
    return sanitized
