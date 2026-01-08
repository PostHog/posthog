import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { CoreEvent } from '~/queries/schema/schema-general'

import { getGoalFilterSummary, getGoalTypeLabel } from './coreEventUtils'

const DEFINE_NEW_CORE_EVENT = '__define_new_core_event__'

export interface CoreEventSelectorProps {
    coreEvents: CoreEvent[]
    value: string | null
    onChange: (coreEvent: CoreEvent | null) => void
    placeholder?: string
    size?: 'small' | 'medium'
    loading?: boolean
    showDefineNewOption?: boolean
    'data-attr'?: string
}

export function CoreEventSelector({
    coreEvents,
    value,
    onChange,
    placeholder = 'Select a core event',
    size = 'small',
    loading = false,
    showDefineNewOption = true,
    'data-attr': dataAttr,
}: CoreEventSelectorProps): JSX.Element {
    const handleChange = (goalId: string | null): void => {
        if (!goalId) {
            onChange(null)
            return
        }
        if (goalId === DEFINE_NEW_CORE_EVENT) {
            router.actions.push(urls.coreEvents())
            return
        }
        const goal = coreEvents.find((g) => g.id === goalId)
        if (goal) {
            onChange(goal)
        }
    }

    const options = coreEvents.map((goal) => ({
        value: goal.id,
        label: goal.name,
        labelInMenu: (
            <div className="flex flex-col">
                <span className="font-medium">{goal.name}</span>
                <span className="text-xs text-muted">
                    {getGoalTypeLabel(goal)}: {getGoalFilterSummary(goal)}
                </span>
            </div>
        ),
    }))

    if (showDefineNewOption) {
        options.push({
            value: DEFINE_NEW_CORE_EVENT,
            label: 'Define new core event',
            labelInMenu: (
                <div className="flex items-center gap-2 text-primary">
                    <IconPlusSmall className="w-4 h-4" />
                    <span>Define new core event</span>
                </div>
            ),
        })
    }

    return (
        <LemonSelect
            size={size}
            placeholder={placeholder}
            options={options}
            onChange={handleChange}
            value={value}
            loading={loading}
            allowClear
            data-attr={dataAttr}
        />
    )
}
