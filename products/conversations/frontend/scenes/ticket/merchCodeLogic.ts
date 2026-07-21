import { JSONContent } from '@tiptap/core'
import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { conversationsTicketsGenerateMerchCodeCreate } from '../../generated/api'
import type { MerchCodeResponseApi } from '../../generated/api.schemas'
import { supportTicketSceneLogic } from './supportTicketSceneLogic'

export interface MerchCodeLogicProps {
    ticketId: string
}

const PRESET_VALUES = [30, 50, 80, 110, 150]

// Ported from the legacy Zendesk "Merch / Discount Code Snippet" macro, with the dollar amount and
// code filled in. Built as TipTap nodes so it drops into the rich-text composer with a live link.
function buildMerchMessageNode(result: MerchCodeResponseApi): JSONContent {
    const amount = Number(result.value_usd)
    const valueText = Number.isInteger(amount) ? String(amount) : amount.toFixed(2)
    return {
        type: 'paragraph',
        content: [
            { type: 'text', text: 'Please feel free to grab yourself some merch from ' },
            { type: 'text', text: 'our merch store', marks: [{ type: 'link', attrs: { href: result.discount_url } }] },
            {
                type: 'text',
                text: ` if you like. If you use that link, it should apply a $${valueText} credit, or you can just enter the code `,
            },
            { type: 'text', text: result.code, marks: [{ type: 'code' }] },
            { type: 'text', text: ` at checkout for $${valueText} off of your purchase!` },
        ],
    }
}

export interface merchCodeLogicValues {
    valueUsd: number
    result: MerchCodeResponseApi | null
    resultLoading: boolean
}

export interface merchCodeLogicActions {
    setValueUsd: (valueUsd: number) => { valueUsd: number }
    generateCode: () => void
    generateCodeSuccess: (result: MerchCodeResponseApi | null) => { result: MerchCodeResponseApi | null }
    generateCodeFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    clearResult: () => { value: true }
    reset: () => { value: true }
    insertIntoComposer: (content: JSONContent) => { content: JSONContent }
    setDraftIsPrivate: (isPrivate: boolean) => { isPrivate: boolean }
}

export type merchCodeLogicType = MakeLogicType<merchCodeLogicValues, merchCodeLogicActions, MerchCodeLogicProps>

export const merchCodeLogic = kea<merchCodeLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'merchCodeLogic']),
    props({} as MerchCodeLogicProps),
    key((props) => props.ticketId),
    connect((props: MerchCodeLogicProps) => ({
        actions: [supportTicketSceneLogic({ id: props.ticketId }), ['insertIntoComposer', 'setDraftIsPrivate']],
    })),
    actions({
        setValueUsd: (valueUsd: number) => ({ valueUsd }),
        clearResult: true,
        reset: true,
    }),
    reducers({
        valueUsd: [
            0,
            {
                setValueUsd: (_, { valueUsd }) => valueUsd,
                reset: () => 0,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        result: [
            null as MerchCodeResponseApi | null,
            {
                generateCode: async () => {
                    const projectId = String(getCurrentTeamId())
                    return await conversationsTicketsGenerateMerchCodeCreate(projectId, props.ticketId, {
                        value_usd: String(values.valueUsd),
                    })
                },
                clearResult: () => null,
                reset: () => null,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setValueUsd: ({ valueUsd }) => {
            // The result card and the composer message are tied to the value the code was minted at,
            // so drop a stale result once the staff member picks a different amount.
            if (values.result && Number(values.result.value_usd) !== valueUsd) {
                actions.clearResult()
            }
        },
        generateCodeSuccess: ({ result }) => {
            if (result) {
                // The merch message is customer-facing, so make sure it lands in a customer reply
                // rather than an internal note if private mode happened to be on.
                actions.setDraftIsPrivate(false)
                actions.insertIntoComposer(buildMerchMessageNode(result))
            }
        },
        generateCodeFailure: ({ error, errorObject }) => {
            const detail =
                errorObject && typeof errorObject === 'object' && 'detail' in errorObject
                    ? (errorObject as { detail: string }).detail
                    : error || 'Failed to generate merch code.'
            lemonToast.error(detail)
        },
    })),
])

export { PRESET_VALUES }
