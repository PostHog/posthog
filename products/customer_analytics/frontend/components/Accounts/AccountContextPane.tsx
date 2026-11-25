import { useActions, useValues } from 'kea'

import * as businessEvolutionPng from '@posthog/brand/hoggies/png/business-evolution'
import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { AccountContextFacts } from './AccountContextFacts'
import { accountContextLogic, type AccountContextLogicProps, type AccountContextResult } from './accountContextLogic'
import { AccountContextSignals } from './AccountContextSignals'
import { AccountContextThreads } from './AccountContextThreads'
import type { AccountViewTileLogicProps } from './accountViewTileConfig'
import { CONTEXT_WRITE_DISABLED_REASON } from './constants'

const HedgehogBusiness = pngHoggie(businessEvolutionPng)

interface EmptyStateCopy {
    title: string
    detail: string
    dataAttr: string
}

const UNAVAILABLE_STATES: Record<Exclude<AccountContextResult['status'], 'loaded' | 'failed'>, EmptyStateCopy> = {
    not_configured: {
        title: "Context isn't set up",
        detail: 'This project has no context source yet. Ask your PostHog admin to connect one.',
        dataAttr: 'account-context-not-set-up',
    },
    no_external_id: {
        title: 'No linked organization',
        detail: 'This account has no linked organization, so there is no context to load.',
        dataAttr: 'account-context-no-external-id',
    },
    no_access: {
        title: "You don't have access to this context",
        detail: "Your account can't read the context source. Ask the person who manages it for access.",
        dataAttr: 'account-context-no-access',
    },
    unreadable: {
        title: "Couldn't read this context",
        detail: "The context source sent data this tab can't read. Ask the person who manages it to check the source.",
        dataAttr: 'account-context-unreadable',
    },
}

interface AccountContextPaneProps extends AccountViewTileLogicProps {
    accountId: string
    externalId: string
    embedded?: boolean
}

function ContextEmptyState({
    title,
    detail,
    action,
    dataAttr,
}: {
    title: string
    detail: string
    action?: JSX.Element
    dataAttr: string
}): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-2 p-8 text-center" data-attr={dataAttr}>
            <HedgehogBusiness className="w-24 h-24" />
            <h4 className="mb-0">{title}</h4>
            <p className="text-secondary max-w-sm mb-0">{detail}</p>
            {action}
        </div>
    )
}

export function AccountContextPane({
    accountId,
    externalId,
    embedded = true,
    ...tileProps
}: AccountContextPaneProps): JSX.Element {
    const logicProps: AccountContextLogicProps = { accountId, externalId, ...tileProps }
    const logic = accountContextLogic(logicProps)
    const { contextResult, contextResultLoading, context } = useValues(logic)
    const { loadContext } = useActions(logic)

    let content: JSX.Element
    if (contextResult === null) {
        content = <LemonSkeleton className="h-64 w-full" />
    } else if (contextResult.status === 'failed') {
        content = (
            <ContextEmptyState
                title="Couldn't load context"
                dataAttr="account-context-load-failed"
                detail="The context source didn't answer. Try again in a minute."
                action={
                    <LemonButton
                        type="secondary"
                        onClick={() => loadContext()}
                        loading={contextResultLoading}
                        data-attr="account-context-retry"
                    >
                        Try again
                    </LemonButton>
                }
            />
        )
    } else if (contextResult.status !== 'loaded') {
        content = <ContextEmptyState {...UNAVAILABLE_STATES[contextResult.status]} />
    } else if (!context || (!context.facts.length && !context.signals.length && !context.threads.length)) {
        content = (
            <ContextEmptyState
                title="No context captured yet"
                dataAttr="account-context-empty"
                detail="Facts, signals and Slack threads show up here after a teammate captures context about this account."
            />
        )
    } else {
        content = (
            <>
                {context.truncated ? (
                    <LemonBanner type="warning">
                        This account has more context than the tab can load. Some facts, topics and reasons are missing.
                    </LemonBanner>
                ) : null}
                <AccountContextFacts logicProps={logicProps} embedded={embedded} />
                <AccountContextSignals logicProps={logicProps} embedded={embedded} />
                <AccountContextThreads logicProps={logicProps} embedded={embedded} />
            </>
        )
    }

    return (
        <div className="ph-no-capture flex flex-col gap-4" data-attr="account-context-pane">
            <div className="flex flex-wrap justify-end gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    disabledReason={CONTEXT_WRITE_DISABLED_REASON}
                    data-attr="account-context-add-fact"
                >
                    Add fact
                </LemonButton>
            </div>
            {content}
        </div>
    )
}
