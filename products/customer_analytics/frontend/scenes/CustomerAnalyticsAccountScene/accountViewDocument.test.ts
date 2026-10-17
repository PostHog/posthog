import type { AccountViewContentApi } from '../../generated/api.schemas'
import {
    createAccountViewContent,
    parseAccountViewContent,
    type AccountViewComponentInstance,
} from './accountViewDocument'

const components: AccountViewComponentInstance[] = [
    {
        nodeId: 'replay-one',
        kind: 'session_replays',
        span: 6,
        title: 'Recent recordings',
        config: { dateRange: { date_from: '-14d', date_to: null } },
    },
]
const savedContent: AccountViewContentApi = {
    type: 'doc',
    content: [
        {
            type: 'ph-markdown-notebook',
            attrs: {
                nodeId: 'markdown-notebook-v2',
                markdown:
                    '<SessionReplays nodeId="replay-one" span={6} title="Recent recordings" config={{"dateRange":{"date_from":"-14d","date_to":null}}} />',
            },
        },
    ],
}

describe('account view document', () => {
    it('reads and writes replay tile dates in saved Markdown', () => {
        expect(parseAccountViewContent(savedContent)).toEqual(components)
        expect(createAccountViewContent(components)).toEqual(savedContent)
    })
})
