# Flox Containerization Guide

Two directions, and they are easy to confuse. This file is mostly about
`flox containerize`, which turns an environment **into** an image. For the
opposite — getting the Flox CLI **into** an image you are already building,
such as a CI agent image or a devcontainer — see
[Installing Flox Into an Image](#installing-flox-into-an-image) near the end.

## Core Commands

```bash
flox containerize                          # Export to default tar file
flox containerize -f ./mycontainer.tar     # Export to specific file
flox containerize --runtime docker         # Export directly to Docker
flox containerize --runtime podman         # Export directly to Podman
flox containerize -f - | docker load       # Pipe to Docker
flox containerize --tag v1.0               # Tag container image
flox containerize -r owner/env             # Containerize remote environment
```

## Basic Usage

### Export to File

```bash
# Export to file
flox containerize -f ./mycontainer.tar
docker load -i ./mycontainer.tar

# Or use default filename: {name}-container.tar
flox containerize
docker load -i myenv-container.tar
```

### Export Directly to Runtime

```bash
# Auto-detects docker or podman
flox containerize --runtime docker

# Explicit runtime selection
flox containerize --runtime podman
```

### Pipe to Stdout

```bash
# Pipe directly to Docker
flox containerize -f - | docker load

# With tagging
flox containerize --tag v1.0 -f - | docker load
```

## How Containers Behave

**Containers activate the Flox environment on startup** (like `flox activate`):

- **Interactive**: `docker run -it <image>` → Bash shell with environment activated
- **Non-interactive**: `docker run <image> <cmd>` → Runs command with environment activated (like `flox activate -- <cmd>`)
- All packages, variables, and hooks are available inside the container

**Note**: Flox sets an entrypoint that activates the environment, then runs `cmd` inside that activation.

## Command Options

```bash
flox containerize
  [-f <file>]           # Output file (- for stdout); defaults to {name}-container.tar
  [--runtime <runtime>] # docker/podman (auto-detects if not specified)
  [--tag <tag>]         # Container tag (e.g., v1.0, latest)
  [-d <path>]           # Path to .flox/ directory
  [-r <owner/name>]     # Remote environment from FloxHub
```

## Manifest Configuration

Configure container in `[containerize.config]` (experimental):

```toml
[containerize.config]
user = "appuser"                    # Username or uid:gid format
exposed-ports = ["8080/tcp"]        # Ports to expose (tcp/udp/default:tcp)
cmd = ["python", "app.py"]          # Command to run (receives activated env)
volumes = ["/data", "/config"]      # Mount points for persistent data
working-dir = "/app"                # Working directory
labels = { version = "1.0" }        # Arbitrary metadata
stop-signal = "SIGTERM"             # Signal to stop container
```

### Configuration Options Explained

**user**: Run container as specific user
- Username: `user = "appuser"`
- UID:GID: `user = "1000:1000"`

**exposed-ports**: Network ports to expose
- TCP: `["8080/tcp"]`
- UDP: `["8125/udp"]`
- Default protocol is tcp: `["8080"]` = `["8080/tcp"]`

**cmd**: Command to run in container
- Array form: `cmd = ["python", "app.py"]`
- Empty for service-based: `cmd = []`

**volumes**: Mount points for persistent data
- List paths: `volumes = ["/data", "/config", "/logs"]`

**working-dir**: Initial working directory
- Absolute path: `working-dir = "/app"`

**labels**: Arbitrary metadata
- Key-value pairs: `labels = { version = "1.0", env = "production" }`

**stop-signal**: Signal to stop container
- Common: `"SIGTERM"`, `"SIGINT"`, `"SIGKILL"`

## Complete Workflow Examples

### Flask Web Application

```bash
# Create environment
flox init
flox install python311 flask

# Configure for container
cat >> .flox/env/manifest.toml << 'EOF'
[containerize.config]
exposed-ports = ["5000/tcp"]
cmd = ["python", "-m", "flask", "run", "--host=0.0.0.0"]
working-dir = "/app"
user = "flask"
EOF

# Build and run
flox containerize -f - | docker load
docker run -p 5000:5000 -v $(pwd):/app <container-id>
```

### Node.js Application

```bash
flox init
flox install nodejs

cat >> .flox/env/manifest.toml << 'EOF'
[containerize.config]
exposed-ports = ["3000/tcp"]
cmd = ["npm", "start"]
working-dir = "/app"
EOF

flox containerize --tag myapp:latest --runtime docker
docker run -p 3000:3000 -v $(pwd):/app myapp:latest
```

### Database Container

```bash
flox init
flox install postgresql

# Set up service in manifest
flox edit

# Add service and container config
cat >> .flox/env/manifest.toml << 'EOF'
[services.postgres]
command = '''
  mkdir -p /data/postgres
  if [ ! -d "/data/postgres/pgdata" ]; then
    initdb -D /data/postgres/pgdata
  fi
  exec postgres -D /data/postgres/pgdata -h 0.0.0.0
'''

[containerize.config]
exposed-ports = ["5432/tcp"]
volumes = ["/data"]
cmd = []  # Service starts automatically
EOF

flox containerize -f - | docker load
docker run -p 5432:5432 -v pgdata:/data <container-id>
```

## Common Patterns

### Service Containers

Services start automatically when cmd is empty:

```toml
[services.web]
command = "python -m http.server 8000"

[containerize.config]
exposed-ports = ["8000/tcp"]
cmd = []  # Service starts automatically
```

### Multi-Stage Pattern

Build in one environment, run in another:

```bash
# Build environment with all dev tools
cd build-env
flox activate -- flox build myapp

# Runtime environment with minimal deps
cd ../runtime-env
flox install myapp
flox containerize --tag production -f - | docker load

# Run
docker run production
```

### Remote Environment Containers

Containerize shared team environments:

```bash
# Containerize remote environment
flox containerize -r team/python-ml --tag latest --runtime docker

# Run it
docker run -it team-python-ml:latest
```

### Multi-Service Container

```toml
[services.db]
command = '''exec postgres -D "$FLOX_ENV_CACHE/postgres"'''

[services.cache]
command = '''exec redis-server'''

[services.api]
command = '''exec python -m uvicorn main:app --host 0.0.0.0'''

[containerize.config]
exposed-ports = ["8000/tcp", "5432/tcp", "6379/tcp"]
cmd = []  # All services start automatically
```

## Platform-Specific Notes

### macOS
- Requires docker/podman runtime (uses proxy container for builds)
- May prompt for file sharing permissions
- Creates `flox-nix` volume for caching
- Safe to remove when not building: `docker volume rm flox-nix`

### Linux
- Direct image creation without proxy
- No intermediate volumes needed
- Native container support

## Advanced Use Cases

### Custom Entrypoint with Wrapper Script

```toml
[build.entrypoint]
command = '''
  cat > $out/bin/entrypoint.sh << 'EOF'
#!/usr/bin/env bash
set -e

# Custom initialization
echo "Initializing application..."
setup_app

# Run whatever command was passed
exec "$@"
EOF
  chmod +x $out/bin/entrypoint.sh
'''

[containerize.config]
cmd = ["entrypoint.sh", "python", "app.py"]
```

### Health Check Support

```toml
[containerize.config]
cmd = ["python", "app.py"]

[containerize.config.labels]
healthcheck = "curl -f http://localhost:8000/health || exit 1"
```

Then in Docker:
```bash
docker run --health-cmd="curl -f http://localhost:8000/health || exit 1" \
           --health-interval=30s \
           myimage
```

### Multi-Architecture Builds

Build for different architectures:

```bash
# On x86_64 Linux
flox containerize --tag myapp:amd64 --runtime docker

# On ARM64 (aarch64) Linux
flox containerize --tag myapp:arm64 --runtime docker

# Create manifest
docker manifest create myapp:latest \
  myapp:amd64 \
  myapp:arm64
```

### Minimal Container Size

Create minimal runtime environment:

```toml
[install]
# Only runtime dependencies
python.pkg-path = "python311"
# No dev tools, no build tools

[build.app]
command = '''
  # Build in build environment
  python -m pip install --target=$out/lib/python -r requirements.txt
  cp -r src $out/lib/python/
'''
runtime-packages = ["python"]

[containerize.config]
cmd = ["python", "-m", "myapp"]
```

## Container Registry Workflows

### Push to Registry

```bash
# Build container
flox containerize --tag myapp:v1.0 --runtime docker

# Tag for registry
docker tag myapp:v1.0 registry.company.com/myapp:v1.0

# Push
docker push registry.company.com/myapp:v1.0
```

### GitLab CI/CD

```yaml
containerize:
  stage: build
  # Flox comes from the job image (ghcr.io/flox/flox), not a step
  script:
    - flox containerize --tag $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG --runtime docker
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG
```

### GitHub Actions

```yaml
# The job needs `permissions: packages: write` — the default workflow
# token is read-only on repositories created since 2023.
- uses: flox/install-flox-action@1128abd73431089ab9d871c893b4e72a729354e1 # v2.6.0

- name: Build and push container
  env:
    IMAGE: ghcr.io/${{ github.repository }}:${{ github.sha }}
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    ACTOR: ${{ github.actor }}
  run: |
    flox containerize --tag "$IMAGE" --runtime docker
    echo "$GH_TOKEN" | docker login ghcr.io -u "$ACTOR" --password-stdin
    docker push "$IMAGE"
```

Both need Flox available and neither needs it activated: `flox containerize`
reads the environment, it does not run inside it. The GitLab job expects a
runner image that already ships Flox, since there is no install action there;
the GitHub job installs it. See `references/ci.md` for the steps that *do* need
an activation, and how to write one.

## Kubernetes Deployment

### Basic Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
      - name: myapp
        image: registry.company.com/myapp:v1.0
        ports:
        - containerPort: 8000
        volumeMounts:
        - name: data
          mountPath: /data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: myapp-data
```

### Service Definition

```yaml
apiVersion: v1
kind: Service
metadata:
  name: myapp
spec:
  selector:
    app: myapp
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

## Debugging Container Issues

### Inspect Container

```bash
# Run interactively
docker run -it --entrypoint /bin/bash <image-id>

# Check environment
docker run <image-id> env

# Check what's in the image
docker run <image-id> ls -la /
```

### View Container Logs

```bash
# Follow logs
docker logs -f <container-id>

# Last 100 lines
docker logs --tail 100 <container-id>
```

### Execute Commands in Running Container

```bash
# Get a shell
docker exec -it <container-id> /bin/bash

# Run specific command
docker exec <container-id> flox list
```

## Installing Flox Into an Image

**Prefer the official image.** `ghcr.io/flox/flox` ships Flox with a working
Nix store and needs no setup. `latest` is maintained and tracks the newest
release, so take it unless the build has to be byte-identical across rebuilds
— then pin a version tag.

```dockerfile
FROM ghcr.io/flox/flox:latest
```

**When the base image is not yours to choose** — a vendor's CI agent image,
say — run the install script in the build:

```dockerfile
FROM buildkite/agent:3-ubuntu

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL https://get.flox.dev | sh \
    && rm -rf /var/lib/apt/lists/*

ENV NIX_REMOTE=auto
```

That image is complete: `flox activate` works in it. Do not reconstruct the
download by hand — an architecture `case` statement plus a
`downloads.flox.dev` URL reimplements what the script already does, against a
path convention you do not own, and pins a version that goes stale. Take the
current release unless something forces otherwise; `FLOX_VERSION` exists for
that case and should not be reached for by default.

The base image must be glibc. The installer dispatches to `apt`/`dpkg` or
`dnf`/`yum` and exits with an error when it finds neither, so Alpine — and the
default musl `buildkite/agent:3` image — is out.

### Why `NIX_REMOTE=auto`, and When It Is Not Enough

During `docker build` there is no `/run/systemd/system` and no running
`systemctl`, so the installer takes its **single-user** path: Nix is installed
with no daemon, and `/nix/store` and `/nix/var/nix` are owned by root.
`NIX_REMOTE=auto` is what makes that store usable — Nix tests whether the state
directory is writable and talks to the store directly when it is, falling back
to the daemon socket only when it is not. The official image sets the same
variable for the same reason.

**A container running as root needs nothing further.** That covers most CI
images, including `buildkite/agent:3-ubuntu`: its config sets no `USER`, there
is no `buildkite-agent` account in it, and a `USER root` line adds nothing.

But root is a property of the **deployment**, not of the image. `docker run
--user`, a Compose `user:`, or a Kubernetes `securityContext.runAsUser` all
override it, and the Buildkite Helm chart and agent-stack-k8s commonly do.
Check before assuming — `docker run --rm <image> id`, and grep your Compose,
Helm or agent config for `--user`, `user:` and `runAsUser`.

**A container whose jobs run as a non-root user needs the daemon**, because
the writability test above then fails and there is no daemon to fall back to:

```
This command may have been run as non-root in a single-user Nix installation,
or the Nix daemon may have crashed.
error: opening lock file '/nix/var/nix/db/big-lock': Permission denied
```

The daemon runs as root and serves unprivileged clients over its socket, which
is what makes a root-owned store usable from a non-root job. Start it from
whatever the image runs before handing off — for the Buildkite agent image
that is `run-parts` over `/docker-entrypoint.d`, which its entrypoint executes
with `--exit-on-error`, so a hook that fails takes the container down with it:

```dockerfile
RUN mkdir -p /docker-entrypoint.d \
    && printf '%s\n' \
      '#!/usr/bin/env bash' \
      'set -euo pipefail' \
      'daemon=/usr/sbin/nix-daemon' \
      'if [ -x "$daemon" ] && ! pgrep -x nix-daemon >/dev/null 2>&1; then' \
      '  "$daemon" >/var/log/nix-daemon.log 2>&1 &' \
      'fi' \
      > /docker-entrypoint.d/10-nix-daemon \
    && chmod +x /docker-entrypoint.d/10-nix-daemon
```

Address the binary by path. The Flox packages install `nix-daemon` to
`/usr/sbin` (a symlink into the store) because it runs as root, and they put
nothing in `/etc/profile.d` — so a hook that sources `/etc/profile.d/nix*.sh`
and then calls `command -v nix-daemon` finds neither. Redirect its output, or
the daemon interleaves with job logs.

Getting this backwards is the failure that hides: an image whose jobs run as a
non-root user looks fine in a root shell at build time and fails on the first
real job.

Once Flox is in the image, entering environments from CI jobs is
`references/ci.md` — the install-is-not-activation split applies the same way
inside a container as on a runner.

## Best Practices

1. **Use specific tags**: Avoid `latest`, use semantic versioning
2. **Minimize layers**: Combine related operations in manifests
3. **Use .dockerignore equivalent**: Only include necessary files in build context
4. **Health checks**: Implement health check endpoints for services
5. **Security**: Run as non-root user when possible
6. **Volumes**: Use volumes for persistent data, not container filesystem
7. **Environment variables**: Make configuration overridable via env vars
8. **Logging**: Log to stdout/stderr, not files

