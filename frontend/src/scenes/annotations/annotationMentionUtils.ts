import { OrganizationMemberType } from '~/types'

/**
 * Extracts mentioned user IDs from annotation content
 * @param content The annotation content to parse
 * @param members Array of team members to match against
 * @returns Array of user IDs that were mentioned
 */
export function extractMentionedUsers(content: string, members: OrganizationMemberType[]): number[] {
    const mentionedUserIds: number[] = []

    // Find all @mentions in the content
    const mentionMatches = content.match(/@[a-zA-Z]+/g)

    if (!mentionMatches) {
        return mentionedUserIds
    }

    // For each mention, find the corresponding user
    mentionMatches.forEach((mention) => {
        const name = mention.slice(1) // Remove the @ symbol

        // Find member by first name (case insensitive)
        const member = members.find((member) => {
            return member.user.first_name.toLowerCase() === name.toLowerCase()
        })

        if (member && !mentionedUserIds.includes(member.user.id)) {
            mentionedUserIds.push(member.user.id)
        }
    })

    return mentionedUserIds
}
