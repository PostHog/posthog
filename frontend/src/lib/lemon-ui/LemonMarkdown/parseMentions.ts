import { OrganizationMemberType } from '~/types'

export interface MentionMatch {
    member: OrganizationMemberType
    displayName: string
    /** The length of the matching user's first name */
    length: number
}

export interface ParsedMentionPart {
    type: 'text' | 'mention'
    /** The content - for text parts this is the text, for mention parts this is the display name */
    content: string
    /** only for mention parts */
    userId?: string
    /** The original text that was matched (for debugging/testing) */
    originalText?: string
}

/**
 * Finds the best matching org member for a given text starting with a potential mention.
 * Uses a greedy approach to find the longest matching first name.
 *
 * @param text - The text after @ symbol to match against
 * @param members - Array of organization members to search through
 * @returns The best matching member and match details, or null if no match found
 */
export function findMentionMatch(text: string, members: OrganizationMemberType[]): MentionMatch | null {
    let bestMatchMember: OrganizationMemberType | null = null

    for (const member of members) {
        const firstName = member.user.first_name

        if (!text.toLowerCase().startsWith(firstName.toLowerCase())) {
            continue
        }

        // Check if this is a complete word match (followed by word boundary or end of string)
        const charAfterName = text[firstName.length]
        const isWordBoundary = !charAfterName || /\s|[^\w]/.test(charAfterName)

        if (!isWordBoundary) {
            continue
        }

        if (firstName.length > (bestMatchMember?.user.first_name || '').length) {
            bestMatchMember = member
        }
    }

    return bestMatchMember
        ? {
              member: bestMatchMember,
              displayName: bestMatchMember.user.first_name,
              length: bestMatchMember.user.first_name.length,
          }
        : null
}

/**
 * Parses a text string and identifies mentions, returning an array of text and mention parts.
 *
 * @param text - The text to parse for mentions
 * @param members - Array of organization members to match against
 * @returns Array of parsed parts (text or mention)
 */
export function parseMentions(text: string, members: OrganizationMemberType[]): ParsedMentionPart[] {
    // Split text by @ to get potential mentions
    const parts = text.split(/(@)/g)
    const result: ParsedMentionPart[] = []

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i]

        if (part === '@' && i + 1 < parts.length) {
            // This is a potential mention start
            const afterAt = parts[i + 1]
            const match = findMentionMatch(afterAt, members)

            if (match) {
                result.push({
                    type: 'mention',
                    content: match.displayName,
                    userId: match.member.user.uuid,
                    originalText: `@${match.displayName}`,
                })

                // Add the remaining text after the mention
                const remainingText = afterAt.slice(match.length)
                if (remainingText) {
                    result.push({
                        type: 'text',
                        content: remainingText,
                    })
                }

                // Skip the next part since we've processed it
                i++
            } else {
                // Not a valid mention, just add @ and continue
                result.push({
                    type: 'text',
                    content: '@',
                })
            }
        } else if (part && part !== '@') {
            // Regular text
            result.push({
                type: 'text',
                content: part,
            })
        }
    }

    return result
}
