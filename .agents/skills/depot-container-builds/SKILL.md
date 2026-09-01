---
name: depot-container-builds
description: >
  Configures and runs Depot remote container builds using `depot build` and `depot bake`.
  Use when building Docker images, creating Dockerfiles with Depot, pushing images to registries,
  building multi-platform/multi-arch images (linux/amd64, linux/arm64), debugging container build
  failures, optimizing Dockerfile layer caching, using docker-bake.hcl or docker-compose builds,
  or migrating from `docker build` / `docker buildx build` to Depot. Also use when the user
  mentions depot build, depot bake, container builds, image builds, or asks about Depot's
  build cache, build parallelism, or ephemeral registry.
---

# Depot Container Builds

Depot runs Docker image builds on remote high-performance builders (16 CPU, 32 GB RAM, NVMe SSD cache). `depot build` is a drop-in replacement for `docker build` / `docker buildx build`. `depot bake` replaces `docker buildx bake`.

## Project Selection for Multi-Org Users

Container build commands target a specific project, not an organization. If expected projects aren't visible or a build unexpectedly prompts to select a project, the current default org may be wrong:

```bash
depot org show              # Current org ID
depot org list              # Orgs the user belongs to
depot org switch <org-id>   # Optional: set default org
```

## Key Concepts

- Builds run remotely on ephemeral EC2 instances — images stay in remote cache by default
- Use `--load` to download to local Docker, `--push` to push to a registry, `--save` to store in Depot's ephemeral registry
- Cache is **fully automatic** on persistent NVMe SSDs — no manual cache config needed
- Multi-platform builds use **native CPU builders** (no QEMU emulation) for amd64 and arm64 simultaneously
- All team members on a project share the same layer cache

## `depot build` — Essential Patterns

```bash
# Build remotely (image stays in remote cache)
depot build -t repo/image:tag .

# Build + download to local Docker daemon
depot build -t repo/image:tag . --load

# Build + push directly to registry (fast — doesn't route through local network)
depot build -t repo/image:tag . --push

# Multi-platform build (native CPUs, no emulation)
depot build --platform linux/amd64,linux/arm64 -t repo/image:tag . --push

# Save to Depot ephemeral registry (7-day default, configurable per repository)
depot build --save .
depot build --save --save-tag my-tag .

# Suppress provenance metadata (fixes "unknown/unknown" platform in registries)
depot build -t repo/image:tag --push --provenance=false .

# Lint Dockerfile before building
depot build -t repo/image:tag . --lint

# Build with secrets
depot build --secret id=mysecret,src=./secret.txt -t repo/image:tag .

# Build with SSH forwarding
depot build --ssh default -t repo/image:tag .

# Specify a Depot project explicitly
depot build --project <project-id> -t repo/image:tag .
```

### Key Flags

| Flag               | Description                                                                                                             |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `--load`           | Download image to local Docker daemon                                                                                   |
| `--push`           | Push to registry                                                                                                        |
| `--save`           | Save to Depot ephemeral registry                                                                                        |
| `--save-tag`       | Custom tag for Depot Registry                                                                                           |
| `--platform`       | Target platforms: `linux/amd64`, `linux/arm64` (native, no emulation), plus `linux/arm/v6`, `linux/arm/v7`, `linux/386` |
| `--build-platform` | Force build to run on specific arch (`dynamic` default)                                                                 |
| `--project`        | Depot project ID                                                                                                        |
| `--token`          | Depot API token                                                                                                         |
| `--lint`           | Lint Dockerfile before build                                                                                            |
| `--provenance`     | Control provenance attestation (set `false` to fix unknown/unknown)                                                     |
| `--sbom`           | Generate an SBOM attestation (shorthand for `--attest type=sbom`)                                                       |
| `--sbom-dir`       | Directory to store SBOM attestations                                                                                    |
| `--attest`         | Attestation parameters (for example `type=sbom,generator=image`)                                                        |
| `--no-cache`       | Disable cache for this build                                                                                            |
| `-f` / `--file`    | Path to Dockerfile                                                                                                      |
| `-t` / `--tag`     | Image name and tag                                                                                                      |
| `--target`         | Build specific stage                                                                                                    |
| `--build-arg`      | Set build-time variables                                                                                                |
| `--secret`         | Expose secrets (`id=name[,src=path]`)                                                                                   |
| `--ssh`            | Expose SSH agent                                                                                                        |
| `--output` / `-o`  | Custom output (`type=local,dest=path`)                                                                                  |

## `depot bake` — Multi-Image Builds

Drop-in replacement for `docker buildx bake`. Builds multiple images in parallel.

```bash
depot bake                                    # Default file lookup
depot bake -f docker-bake.hcl                 # Specific HCL file
depot bake -f docker-compose.yml --load       # Build compose services + load locally
depot bake --save --save-tag myrepo/app:v1    # Save to Depot Registry
depot bake --print                            # Print resolved config without building
```

**Default file lookup order:** compose.yaml → compose.yml → docker-compose.yml → docker-compose.yaml → docker-bake.json → docker-bake.hcl → docker-bake.override.json → docker-bake.override.hcl

### HCL Bake File Example

```hcl
variable "TAG" {
  default = "latest"
}

group "default" {
  targets = ["app", "worker"]
}

target "app" {
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = ["myrepo/app:${TAG}"]
  args = { NODE_VERSION = "20" }
}

target "worker" {
  dockerfile = "Dockerfile.worker"
  tags       = ["myrepo/worker:${TAG}"]
  contexts   = { app = "target:app" }  # Share base between targets
}
```

Override variables: `TAG=v2.0 depot bake`

### Docker Compose with Per-Service Project IDs

```yaml
services:
  api:
    build:
      dockerfile: ./Dockerfile.api
      x-depot:
        project-id: abc123
  web:
    build:
      dockerfile: ./Dockerfile.web
      x-depot:
        project-id: def456
```

## Docker Compose Integration

```bash
# Preferred: build all services in parallel, then load
depot bake -f docker-compose.yml --load
docker compose up

# Alternative: zero code change (less efficient, each service = separate build)
depot configure-docker
docker compose build
```

## Migration from Docker

```bash
# docker build → depot build (same flags, one-line swap)
depot build -t my-image .

# docker buildx bake → depot bake
depot bake -f docker-bake.hcl

# Zero code change via Docker plugin
depot configure-docker
docker build .  # Routes through Depot (look for [depot] prefix in logs)
```

**When migrating, remove these flags** — Depot handles caching automatically:

- `--cache-from type=gha` — causes "services aren't available" errors
- `--cache-to type=gha` — same issue
- Any manual BuildKit cache configuration

## Common Mistakes

| Mistake                                                | Fix                                                                                                                             |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| Using `--cache-from type=gha` or `--cache-to type=gha` | Remove them. Depot caches automatically on NVMe SSDs.                                                                           |
| Multi-platform image shows `unknown/unknown` platform  | Add `--provenance=false`                                                                                                        |
| Expecting image locally after `depot build`            | Add `--load` to download, or `--push` to push to registry                                                                       |
| `.git` directory missing in build context              | Add `--build-arg BUILDKIT_CONTEXT_KEEP_GIT_DIR=1`                                                                               |
| Build hangs or "failed to mount" errors                | Reset cache in project settings or via `depot cache reset`                                                                      |
| "401 Unauthorized" pulling base images                 | Docker Hub rate limit — authenticate with `docker login` or use `public.ecr.aws/docker/library/` mirror                         |
| `--load` fails with "client version 1.43 is too old"   | Docker Engine v29 raised the minimum API version to 1.44 — prefix the build with `DOCKER_API_VERSION=1.52 depot build --load .` |
| "Keep alive ping failed" / OOM                         | Scale up builder size in project settings or enable autoscaling                                                                 |

## Builder Sizes

| Size        | CPUs | RAM    | Per-Minute | Minutes multiplier | Plans    |
| ----------- | ---- | ------ | ---------- | ------------------ | -------- |
| Default     | 16   | 32 GB  | $0.04      | 1x                 | All      |
| Large       | 32   | 64 GB  | $0.08      | 2x                 | Startup+ |
| Extra Large | 64   | 128 GB | $0.16      | 4x                 | Startup+ |

Billed per-second. Large and Extra Large builders consume your included build minutes faster (via the multiplier) in addition to costing more per minute.

## Depot Registry

An OCI-compliant registry that works both as a lightweight ephemeral store for build output and as a full primary registry for all your images (including ones not built with Depot). Each org gets its own subdomain `{orgId}.registry.depot.dev`, backed by a global CDN, and stores images and OCI artifacts (Helm charts, AI models) up to 50 GB. Browse repositories, tags, and attestations in the Registry Explorer in the dashboard.

```bash
# Save a Depot build's output to the registry (project-scoped, no tagging step)
depot build --save -t myapp .

# Push any image to Depot Registry as a primary registry
docker push {orgId}.registry.depot.dev/your/app:v1

# Pull a saved image (by build ID or by tag)
depot pull --project <id> <build-id>
depot pull --project <id> my-image:tag
depot pull --project <id> --platform linux/arm64 <build-id>   # pull a specific platform

# Generate a short-lived (1-hour) read-only token to pull from the Depot Registry
depot pull-token --project <id>
depot pull-token --project <id> <build-id>                    # scoped to a specific build

# Push saved image to another registry
depot push --project <id> -t registry/image:tag <build-id>

# Docker auth for Depot Registry (each org has its own subdomain)
docker login {orgId}.registry.depot.dev -u x-token -p <depot-token>
# Registry URL: {orgId}.registry.depot.dev/your/app:tag
# (the legacy registry.depot.dev/<project-id>:<build-id> form still works for existing usage)
```

Image retention defaults to 7 days but is configurable per repository from the Registry Explorer, either by age (1, 7, 14, or 30 days) or by tag count (5, 10, 25, 50, or 100 tags).

**Pull-through cache:** Depot Registry can proxy an external registry and cache its layers on the CDN, so repeat pulls skip the upstream hop (faster CI pulls, global distribution, simpler auth for registries like Google Artifact Registry). Configure an upstream in Registry Settings; supported providers are Docker Hub, GitHub Container Registry, GitLab Container Registry, Quay.io, AWS ECR, Google Artifact Registry, Azure Container Registry, and custom registries. Pull-through must be set when the repository is created, it can't be added to an existing repository.

## Special Output Formats

```bash
# estargz (lazy-pulling for faster container startup)
depot build --output "type=image,name=repo/image:tag,push=true,compression=estargz,oci-mediatypes=true,force-compression=true" .

# zstd compression (faster Fargate/K8s startup)
depot build --output type=image,name=repo/image:tag,oci-mediatypes=true,compression=zstd,compression-level=3,force-compression=true,push=true .

# SOCI v2 (lazy-loading for faster startup of large images, for example CUDA/PyTorch)
depot build -t repo/image:tag --push --output type=image,soci=true,compression=gzip,force-compression=true,oci-mediatypes=true .
```

SOCI only indexes gzip layers, so `compression=gzip` is required and `force-compression=true` ensures every layer (including base-image layers) is indexed. The index is written alongside unchanged layers in the registry, so there's no separate post-push step; layers under 10 MB are skipped by default (`soci-min-layer-size` to change). To get the startup benefit, the pulling platform must use the SOCI snapshotter: AWS Fargate does this automatically, and Amazon EKS/EC2 or your own hosts need the soci-snapshotter enabled in containerd.
