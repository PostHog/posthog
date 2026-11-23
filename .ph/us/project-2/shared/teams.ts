// Team inputs from the terragrunt.hcl of each team under terraform/us/project-2/. Only values, so a
// stack imports them without importing another stack's definitions.
export const analyticsPlatform = {
    slackChannelId: 'C09S5802LMU',
    slackWorkspaceId: 54567,
    alertSubscribedUserIds: [339134],
}

export const billing = {
    // #alerts-billing
    slackChannelId: 'C039XEY25ML',
    slackWorkspaceId: 173069,
    alertMentionSlackUserIds: ['U0BLTRYPJ3D'],
}

export const tags = { managed: 'managed-by:terraform', slo: 'slo' }
