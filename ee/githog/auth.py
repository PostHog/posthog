from github.Installation import Installation
import jwt
import requests
import time
import os
import github

def load_private_key():
    PRIVATE_KEY_PATH = "./githog-cert.pem"
    try:
        with open(PRIVATE_KEY_PATH, "r") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Error: Private key file '{PRIVATE_KEY_PATH}' not found.")
        exit(1)
    except Exception as e:
        print(f"Error reading private key file: {e}")
        exit(1)


def generate_jwt():
    PRIVATE_KEY = load_private_key()
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + (10 * 60),  # Token valid for 10 minutes
        "iss": APP_ID,
    }
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256")

def get_installation_token(installation_id: int):
    jwt_token = generate_jwt()
    response = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {jwt_token}", "Accept": "application/vnd.github.v3+json"},
    )
    if response.status_code == 201:
        return response.json().get("token")
    else:
        print(f"Error fetching installation token: {response.json()}")
        exit(1)

def get_installation(installation_id: int) -> Installation:
    PRIVATE_KEY = load_private_key()
    APP_ID = os.getenv("GITHUB_APP_ID")

    if not APP_ID:
        print("GITHUB_APP_ID is not set")
        exit(1)

    auth = github.Auth.AppAuth(APP_ID, PRIVATE_KEY)

    gh_integration = github.GithubIntegration(auth=auth)

    installation = gh_integration.get_app_installation(installation_id)
    return installation