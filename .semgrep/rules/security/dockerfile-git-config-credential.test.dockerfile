# fixture for dockerfile-git-config-credential
FROM debian:bookworm-slim

# ruleid: dockerfile-git-config-credential
RUN git config --global url."https://${GITHUB_TOKEN}@github.com/".insteadOf "git@github.com:"

# ruleid: dockerfile-git-config-credential
RUN git config --global url."https://x-access-token:${APP_TOKEN}@github.com/org/repo".insteadOf "ssh://git@github.com/org/repo"

# credential-free URL rewrites are fine
# ok: dockerfile-git-config-credential
RUN git config --global url."https://github.com/".insteadOf "git@github.com:"

# ok: dockerfile-git-config-credential
RUN git config --global init.defaultBranch main