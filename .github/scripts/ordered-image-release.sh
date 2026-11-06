#!/usr/bin/env bash
set -uo pipefail

compute_tag() {
    if [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" != "false" ]; then
        echo "::warning title=Ordered release tag skipped::The checkout must fetch full history."
        return 0
    fi
    if ! head_revision="$(git rev-parse HEAD)" || [ "$head_revision" != "$GITHUB_SHA" ]; then
        echo "::warning title=Ordered release tag skipped::The checked-out revision does not match GITHUB_SHA."
        return 0
    fi
    if ! position="$(git rev-list --first-parent --count "$GITHUB_SHA")"; then
        echo "::warning title=Ordered release tag skipped::The source position could not be computed."
        return 0
    fi
    if ! [[ "$position" =~ ^[1-9][0-9]{0,11}$ ]]; then
        echo "::warning title=Ordered release tag skipped::The source position is out of range."
        return 0
    fi
    if ! printf -v tag 'r%012d-%.6s' "$position" "$GITHUB_SHA"; then
        echo "::warning title=Ordered release tag skipped::The source position could not be formatted."
        return 0
    fi
    if ! [[ "$tag" =~ ^r[0-9]{12}-[0-9a-f]{6}$ ]]; then
        echo "::warning title=Ordered release tag skipped::${tag} does not match the required format."
        return 0
    fi
    echo "tag=${tag}" >> "$GITHUB_OUTPUT"
}

install_regctl() {
    local executable="$1" asset checksum
    case "$(uname -s)/$(uname -m)" in
        Linux/x86_64) asset=regctl-linux-amd64; checksum=8e0e62a497fcdb8048d18aa927a139613176ba0531f412bc541044e28f9856bd ;;
        Darwin/arm64) asset=regctl-darwin-arm64; checksum=5b52b71861abc300ab513e87a4c3794cff6508035ac7f6b6bdfa1fa5688c0040 ;;
        *) echo 'Unsupported regctl platform' >&2; return 1 ;;
    esac
    curl --fail --location --retry 2 --retry-all-errors --connect-timeout 10 --max-time 15 \
        "https://github.com/regclient/regclient/releases/download/v0.11.6/$asset" -o "$executable" || return 1
    printf '%s  %s\n' "$checksum" "$executable" | shasum -a 256 --check || return 1
    chmod 755 "$executable"
}

validate_timeout() {
    if ! [[ "$1" =~ ^[1-9][0-9]{0,2}$ ]]; then
        echo 'Invalid ordered image publication timeout' >&2
        return 1
    fi
}

readback() {
    local readback_status=0 readback_seconds="${READBACK_TIMEOUT_SECONDS:-40}"
    validate_timeout "$readback_seconds" || return 1
    resolved_digest="$(timeout --foreground --kill-after=5s "${readback_seconds}s" aws ecr batch-get-image \
        --registry-id "${ECR_REGISTRY%%.*}" \
        --repository-name "$ECR_REPO" \
        --image-ids imageTag="$ORDERED_ALIAS" \
        --accepted-media-types \
            "application/vnd.oci.image.index.v1+json" \
            "application/vnd.docker.distribution.manifest.list.v2+json" \
            "application/vnd.oci.image.manifest.v1+json" \
            "application/vnd.docker.distribution.manifest.v2+json" \
        --query 'images[0].imageId.imageDigest' --output text)" || readback_status=$?
    if [ "$readback_status" -ne 0 ]; then
        result=unknown
    elif [ "$resolved_digest" = "None" ]; then
        result=absent
    elif [[ "$resolved_digest" =~ ^sha256:[0-9a-f]{64}$ ]] && [ "$resolved_digest" = "${EXPECTED_DIGEST:-}" ]; then
        result=present-at-expected-digest
    elif [[ "$resolved_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
        result=integrity-mismatch
    else
        result=unknown
    fi
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "outcome=$result" >> "$GITHUB_OUTPUT"
    fi
}

read_alias() {
    if [ -z "${ECR_REGISTRY:-}" ] || [ -z "${ECR_REPO:-}" ] || [ -z "${ORDERED_ALIAS:-}" ]; then
        echo 'Ordered image read requires a registry, repository and alias' >&2
        return 1
    fi
    local resolved_digest result
    readback || return 1
    printf '%s\n' "$resolved_digest"
    if [ "$result" = unknown ]; then
        echo 'Ordered image readback unavailable' >&2
        return 1
    fi
}

publish_alias() {
    if [ -z "${EXPECTED_DIGEST:-}" ]; then
        echo "::warning title=Ordered image alias source digest unavailable::Ordered image alias publication was skipped because no image digest was resolved."
        return 0
    fi
    if [ -z "${ECR_REGISTRY:-}" ] || [ -z "${ECR_REPO:-}" ]; then
        echo "::warning title=Ordered image alias destination unavailable::Ordered image alias publication was skipped because the ECR registry or repository name resolved empty."
        return 0
    fi
    if [ -z "${REGCTL:-}" ]; then
        echo "::warning title=Ordered image alias copy client unavailable::Ordered image alias publication was skipped because no copy client was supplied."
        return 0
    fi
    if { [ -n "${SOURCE_REGISTRY:-}" ] && [ -z "${SOURCE_REPO:-}" ]; } ||
        { [ -z "${SOURCE_REGISTRY:-}" ] && [ -n "${SOURCE_REPO:-}" ]; }; then
        echo "::warning title=Ordered image alias source unavailable::Ordered image alias publication was skipped because the source registry and repository must be supplied together."
        return 0
    fi
    local source_image="${SOURCE_REGISTRY:-$ECR_REGISTRY}/${SOURCE_REPO:-$ECR_REPO}@${EXPECTED_DIGEST}"
    local target_image="${ECR_REGISTRY}/${ECR_REPO}:${ORDERED_ALIAS}"
    local publication_status=0 resolved_digest result
    local copy_seconds="${COPY_TIMEOUT_SECONDS:-40}" readback_seconds="${READBACK_TIMEOUT_SECONDS:-40}"
    validate_timeout "$copy_seconds" || return 1
    validate_timeout "$readback_seconds" || return 1
    timeout --foreground --kill-after=5s "${copy_seconds}s" "$REGCTL" image copy \
        "$source_image" "$target_image" || publication_status=$?
    if [ "$publication_status" -ne 0 ]; then
        echo "::warning::Ordered alias publication exited with status $publication_status"
    fi
    readback || return 1
    case "$result" in
        present-at-expected-digest)
            echo "::notice title=Ordered image alias present::The ordered image alias resolves to the expected image digest." ;;
        absent)
            echo "::warning title=Ordered image alias absent::The ordered image alias is absent after publication." ;;
        integrity-mismatch)
            echo "::error title=Ordered image alias integrity mismatch::The ordered image alias resolves to a different image digest." ;;
        unknown)
            echo "::error title=Ordered image alias read-back unavailable::The ordered image alias could not be read back from ECR." ;;
    esac
}

case "${1:-}" in
    tag) compute_tag ;;
    install) install_regctl "$2" ;;
    read) read_alias ;;
    publish) publish_alias ;;
    *) echo 'usage: ordered-image-release.sh tag|install PATH|read|publish' >&2; exit 2 ;;
esac
