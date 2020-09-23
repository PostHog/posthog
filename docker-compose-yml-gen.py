import secrets
import string
from typing import Optional

import yaml

HOST_PORT_DEFAULT = 80


def generate_secret_key() -> str:
    """Generate securely random 50 ASCII letters and digits."""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(50)
    )  # random 50 ASCII letters and digits


def save_yml(*, host_port: int, secret_key: str):
    with open("docker-compose.yml", "w") as file:
        yaml.dump(
            {
                "version": "3",
                "services": {
                    "db": {
                        "container_name": "posthog_db",
                        "environment": {
                            "POSTGRES_DB": "posthog",
                            "POSTGRES_PASSWORD": "posthog",
                            "POSTGRES_USER": "posthog",
                        },
                        "image": "postgres:alpine",
                    },
                    "redis": {"container_name": "posthog_redis", "image": "redis:alpine"},
                    "web": {
                        "container_name": "posthog_web",
                        "depends_on": ["db", "redis"],
                        "environment": {
                            "DATABASE_URL": "postgres://posthog:posthog@db:5432/posthog",
                            "IS_DOCKER": "true",
                            "REDIS_URL": "redis://redis:6379/",
                            "SECRET_KEY": secret_key,
                        },
                        "image": "posthog/posthog:latest",
                        "links": ["db:db", "redis:redis"],
                        "ports": [f"{host_port}:8000"],
                    },
                },
            },
            stream=file,
            indent=4,
        )


def main():
    host_port: Optional[int] = None
    secret_key: Optional[str] = None

    print("Let's generate the right production-ready docker-compose.yml for your PostHog instance.\n")

    print("If you're OK with a question's default, you can skip by pressing Enter/Return.\n")

    print(
        f"On which host port should the PostHog server be exposed?\n"
        "Leave on default value 80 if not using a reverse proxy such as nginx.\n"
        "Otherwise select a higher-numbered port (like 8000) and point your reverse proxy server to it.\n"
    )
    while True:
        try:
            host_port_raw = input()
            host_port = int(host_port_raw) if host_port_raw else HOST_PORT_DEFAULT
        except ValueError:
            print("Port must be a number! Please try again.\n")
        else:
            break

    print(
        f"\nDo you have a specific Django SECRET_KEY?\n"
        "Django uses the SECRET_KEY variable for e.g. encrypting sessions and tokens,\n"
        "so it's important that it is secret and only yours.\n"
        "If you don't need a specific key, skip this and let us generate you one.\n"
    )
    secret_key = input() or "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(50))

    save_yml(host_port=host_port, secret_key=secret_key)

    print("\nThank you! Generated docker-compose.yml. You can now use it in production.")


if __name__ == "__main__":
    main()
