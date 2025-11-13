#!/usr/bin/env node

// Post Vercel-style preview comment on PR
// Requires: github, context from actions/github-script
// Args: prNumber, triggerStatus, deploymentUrl, deploymentId

module.exports = async ({github, context, prNumber, triggerStatus, deploymentUrl, deploymentId}) => {
  const commentHash = `[docs-preview]: #docs-preview-${prNumber}`;

  // Delete old preview comments by finding our hash
  const comments = await github.rest.issues.listComments({
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: prNumber
  });

  for (const comment of comments.data) {
    if (comment.user.login === 'github-actions[bot]' && comment.body.includes('[docs-preview]:')) {
      await github.rest.issues.deleteComment({
        owner: context.repo.owner,
        repo: context.repo.repo,
        comment_id: comment.id
      });
    }
  }

  // Format timestamp like Vercel (UTC)
  const now = new Date();
  const timestamp = now.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'UTC'
  });

  let message = '';

  if (triggerStatus === 'success') {
    const previewUrl = deploymentUrl || 'https://posthog.com';
    const inspectorUrl = deploymentId ? `https://vercel.com/post-hog/posthog/${deploymentId}` : 'https://vercel.com/post-hog/posthog';

    message = `${commentHash}\nDocs from this PR will be published at posthog.com\n\n` +
              `| Project | Deployment | Preview | Updated (UTC) |\n` +
              `| :--- | :----- | :------ | :------ |\n` +
              `| [posthog.com](${inspectorUrl}) | 🤷 Unknown | [Preview](${previewUrl}) | ${timestamp} |\n\n` +
              `*Preview will be ready in ~10 minutes. Click Preview link above to access docs at \`/handbook/engineering/\`*`;
  } else {
    message = `${commentHash}\n⚠️ **Docs Preview Build Failed**\n\n` +
              `Preview build could not be triggered. Check the [GitHub Action logs](https://github.com/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}) for details.`;
  }

  await github.rest.issues.createComment({
    issue_number: prNumber,
    owner: context.repo.owner,
    repo: context.repo.repo,
    body: message
  });
};
