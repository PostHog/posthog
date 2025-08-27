import requests


def send_request(path, method, params=None, payload=None):
    token = "token"
    if not token:
        raise ValueError("AIRBYTE_API_KEY must be set in order to create a source.")

    headers = {"accept": "application/json", "content-type": "application/json", "Authorization": f"Bearer {token}"}

    if method == "GET":
        response = requests.get(path, params=params, headers=headers)
    elif method == "POST":
        response = requests.post(path, json=payload, headers=headers)
    elif method == "PATCH":
        response = requests.patch(path, json=payload, headers=headers)
    elif method == "DELETE":
        response = requests.delete(path, headers=headers)
        return
    else:
        raise ValueError(f"Invalid method: {method}")

    response_payload = response.json()

    if not response.ok:
        raise ValueError(response_payload["detail"])

    return response_payload
