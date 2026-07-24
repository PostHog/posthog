import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconChevronDown, IconPlus, IconSparkles } from '@posthog/icons'
import { LemonButton, type LemonButtonProps } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutCreateInitialValues } from '../../../logics/scoutCreateModalLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SCOUT_AUTHOR_PROMPT } from '../../../utils/scoutRunsWindow'

const LazyScoutCreateModal = React.lazy(async () => {
    const { ScoutCreateModal } = await import('./ScoutCreateModal')
    return { default: ScoutCreateModal }
})

export interface ScoutCreateButtonProps {
    children?: React.ReactNode
    className?: string
    initialValues?: ScoutCreateInitialValues
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
    size?: LemonButtonProps['size']
    type?: LemonButtonProps['type']
    'data-attr'?: string
}

export function ScoutCreateButton({
    initialValues,
    onCreated,
    children = 'Create scout with AI',
    className,
    size = 'small',
    type = 'primary',
    'data-attr': dataAttr,
}: ScoutCreateButtonProps): JSX.Element {
    const [isManualModalOpen, setIsManualModalOpen] = useState(false)
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { runningChatPrompt } = useValues(scoutFleetLogic)
    const isStartingAiTask = runningChatPrompt === SCOUT_AUTHOR_PROMPT
    const anotherChatTaskIsStarting = runningChatPrompt !== null && !isStartingAiTask
    const creationDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmSkill,
        AccessControlLevel.Editor
    )

    return (
        <>
            <LemonButton
                type={type}
                size={size}
                icon={<IconSparkles />}
                loading={isStartingAiTask}
                disabledReason={
                    anotherChatTaskIsStarting ? 'Starting another task…' : (creationDisabledReason ?? undefined)
                }
                onClick={() => startScoutChatTask(SCOUT_AUTHOR_PROMPT, 'scout authoring task', 'Create scout with AI')}
                sideAction={{
                    icon: <IconChevronDown />,
                    'aria-label': 'Alternative ways to create a scout',
                    tooltip: 'Alternative ways to create a scout',
                    dropdown: {
                        placement: 'bottom-end',
                        overlay: (
                            <LemonButton
                                fullWidth
                                size={size}
                                icon={<IconPlus />}
                                disabledReason={creationDisabledReason}
                                onClick={() => setIsManualModalOpen(true)}
                            >
                                Create manually
                            </LemonButton>
                        ),
                    },
                }}
                className={className}
                data-attr={dataAttr}
            >
                {children}
            </LemonButton>
            {isManualModalOpen ? (
                <React.Suspense fallback={null}>
                    <LazyScoutCreateModal
                        isOpen
                        initialValues={initialValues}
                        onCreated={onCreated}
                        onClose={() => setIsManualModalOpen(false)}
                    />
                </React.Suspense>
            ) : null}
        </>
    )
}
