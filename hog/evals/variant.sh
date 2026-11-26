#!/bin/sh
# Builds hog from this checkout and writes one Dockerfile per scenario that runs it, for comparing a change
# against the release. Run `hog/evals/mock/start.sh` first.
#
#   hog/evals/variant.sh no-purpose
#   bun hog/evals/stunthog.ts --variant no-purpose --run --only handoff
#
# SKILLS_ZIP=<path> also serves that context-mill `skills-mcp-resources.zip` to hog instead of the release.
set -eu

name=${1:?Name the variant, such as hog/evals/variant.sh no-purpose}
here=$(cd "$(dirname "$0")" && pwd)
env="$here/.generated/env"
[ -f "$env/Dockerfile.approve" ] || { echo "Run hog/evals/mock/start.sh first." >&2; exit 1; }

case $(docker info --format '{{.Architecture}}') in
    aarch64 | arm64) target=bun-linux-arm64 ;;
    *) target=bun-linux-x64-baseline ;;
esac

cd "$here/.."
pnpm run build:mcp >/dev/null
bun build --compile --target="$target" --no-compile-autoload-dotenv --no-compile-autoload-bunfig \
    src/index.ts --outfile "$env/hog-$name" >/dev/null

skills=""
if [ -n "${SKILLS_ZIP:-}" ]; then
    cp "$SKILLS_ZIP" "$env/skills-$name.zip"
    skills="COPY skills-$name.zip /opt/hog-skills.zip
ENV POSTHOG_MCP_LOCAL_SKILLS_URL=file:///opt/hog-skills.zip"
fi

for scenario in approve never denied quiet; do
    {
        cat "$env/Dockerfile.$scenario"
        printf '\n# hog built from %s for the %s variant.\nCOPY hog-%s /usr/local/bin/hog\n%s\n' \
            "$(git rev-parse --short HEAD)" "$name" "$name" "$skills"
    } >"$env/Dockerfile.$scenario-$name"
done

echo "Built hog $name from $(git rev-parse --short HEAD). Run: bun hog/evals/stunthog.ts --variant $name --run"
