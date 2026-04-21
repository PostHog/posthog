#!/usr/bin/env node

const { execSync } = require('child_process')

const [prNumber, repo, commitSha, snapshotSha] = process.argv.slice(2)

if (process.argv.length < 5 || process.argv.length > 6) {
    console.error('Usage: post-openapi-comment.js <pr_number> <repo> <commit_sha> [snapshot_sha]')
    process.exit(1)
}

const comment = `### Generated types: OpenAPI types updated

OpenAPI generated types have been automatically updated to match current serializers.

**Next steps:**
- Review the generated type changes to ensure they're intentional
- If unexpected, investigate what serializer or viewset change caused it

[Review generated type changes →](https://github.com/${repo}/commit/${snapshotSha || commitSha})`

try {
    execSync(`gh pr comment ${prNumber} --repo ${repo} --body-file -`, {
        input: comment,
        encoding: 'utf-8',
        stdio: ['pipe', 'inherit', 'inherit'],
    })
    console.error(`Posted OpenAPI comment to PR #${prNumber}`)
} catch (error) {
    console.error(`Failed to post comment: ${error.message}`)
    process.exit(1)
}
