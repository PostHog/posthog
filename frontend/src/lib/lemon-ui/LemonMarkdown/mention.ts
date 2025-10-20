// @ts-nocheck
// TODO: Remark plugin typing isn't great so opting to skip it wholesale in this file
import { findAndReplace } from 'mdast-util-find-and-replace'

import { RichContentNodeType } from 'lib/components/RichContentEditor/types'

const mentionRegex = new RegExp(/(?:^|\s)@(member|role):(\d+)/, 'gi')

export default function remarkMentions() {
    const replaceMention = (
        value: string,
        mentionType: string,
        id: string
    ): { type: string; mentionType: string; id: number }[] => {
        let whitespace = []

        // Separate leading white space
        if (value.indexOf('@') > 0) {
            whitespace.push({
                type: 'text',
                value: value.substring(0, value.indexOf('@')),
            })
        }

        return [
            ...whitespace,
            {
                type: RichContentNodeType.Mention,
                mentionType,
                id: parseInt(id),
            },
        ]
    }

    return (tree) => {
        findAndReplace(tree, [[mentionRegex, replaceMention]])
    }
}
