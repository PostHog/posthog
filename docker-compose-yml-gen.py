import secrets
import string
from typing import Optional

import yaml
from yaml.loader import FullLoader

FILE_PATH = "docker-compose.yml"


def generate_secret_key() -> str:
    """Securely generate random 50 ASCII letters and digits."""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(50)
    )  # random 50 ASCII letters and digits


def save_yml(*, host_port: int, secret_key: str):
    with open(FILE_PATH, "r") as file:
        config = yaml.load(file, Loader=FullLoader)
    if not config:
        raise ValueError("Cannot edit a malformed docker-compose.yml! Get a fresh one from the PostHog repository.")
    with open(FILE_PATH, "w") as file:
        config["services"]["web"]["ports"] = [f"{host_port}:8000"]
        config["services"]["web"]["environment"]["SECRET_KEY"] = secret_key
        yaml.dump(
            config, stream=file, indent=4,
        )


def input_host_port(n: int, default: int = 80) -> int:
    print(
        f"{n}. On which host port should the PostHog server be exposed? ({default})\n"
        "Leave on default value 80 if not using a reverse proxy such as nginx.\n"
        "Otherwise select a higher-numbered port (like 8000)\n"
        "and point your reverse proxy server to it.\n"
    )
    while True:
        try:
            host_port_raw = input()
            return int(host_port_raw) if host_port_raw else default
        except ValueError:
            print("Port must be a number! Please try again.\n")


def input_secret_key(n: int) -> str:
    print(
        f"{n}. Do you have a specific Django SECRET_KEY? (random)\n"
        "Django uses the SECRET_KEY variable for e.g. encrypting sessions and tokens,\n"
        "so it's important that it is secret and only yours.\n"
        "If you don't have one already, skip this and let us generate you one.\n"
    )
    return input() or "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(50))


def main():
    host_port: Optional[int] = None
    secret_key: Optional[str] = None

    print("Let's build the right production docker-compose.yml for your PostHog instance.\n")

    print("If you're OK with a step's default value (in parentheses),\n" "you can skip it by pressing Enter/Return.\n")

    host_port = input_host_port(1)
    secret_key = input_secret_key(2)

    save_yml(host_port=host_port, secret_key=secret_key)

    print("\nGenerated and saved docker-compose.yml. You can now use it in production.")


if __name__ == "__main__":
    main()
