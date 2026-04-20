import os

import dagster


@dagster.asset
def postgres_env_check(context: dagster.AssetExecutionContext) -> None:
    """
    Simple asset that prints PostgreSQL environment variables being used.
    Useful for debugging connection configuration.
    """
    env_vars = {
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "not set"),
        "POSTGRES_PORT": os.getenv("POSTGRES_PORT", "not set"),
        "POSTGRES_DATABASE": os.getenv("POSTGRES_DATABASE", "not set"),
        "POSTGRES_USER": os.getenv("POSTGRES_USER", "not set"),
        "POSTGRES_PASSWORD": "***" if os.getenv("POSTGRES_PASSWORD") else "not set",
    }

    context.log.info("PostgreSQL environment variables:")
    for key, value in env_vars.items():
        context.log.info(f"  {key}: {value}")
