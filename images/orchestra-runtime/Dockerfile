# Base image for user-deployed orchestra worker containers.
#
# Built once per PostHog commit by bin/build-orchestra-runtime. Per-deploy
# images FROM this base and COPY user code into /user-code at build time.
#
# Build from the repo root:
#   docker build -t posthog/orchestra-runtime:latest -f images/orchestra-runtime/Dockerfile .

FROM python:3.12-slim

# Engine deps mirror products/orchestra/backend/engine/db.py imports.
RUN pip install --no-cache-dir "psycopg[binary,pool]>=3.2"

# Bake in the engine as a self-contained package: `orchestra_engine`. The runtime
# entrypoint and per-deploy images only need this, not the rest of the PostHog tree.
COPY products/orchestra/backend/engine/ /app/orchestra_engine/
COPY images/orchestra-runtime/runtime_main.py /app/orchestra_runtime.py

WORKDIR /app
ENV PYTHONPATH=/app:/user-code
ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/orchestra_runtime.py"]
