import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

function getNestedValue(obj: Record<string, any> | undefined | null, path: string): any {
    if (!obj) {
        return undefined
    }
    const parts = path.split('.')
    let current: any = obj
    for (const part of parts) {
        if (current == null) {
            return undefined
        }
        current = current[part]
    }
    return current
}

function buildNestedUpdate(path: string, value: any, existingRoot?: Record<string, any>): Record<string, any> {
    const parts = path.split('.')
    if (parts.length === 1) {
        return { [parts[0]]: value }
    }
    // For nested paths like "modifiers.personsJoinMode", build { modifiers: { ...existing, personsJoinMode: value } }
    const rootKey = parts[0]
    const restPath = parts.slice(1).join('.')
    const existingNested = existingRoot?.[rootKey] ?? {}
    return { [rootKey]: { ...existingNested, ...buildNestedUpdate(restPath, value, existingNested) } }
}

export function TeamSettingRadio<T extends string>({
    field,
    options,
    defaultValue,
    onSave,
}: {
    /** Dot-path to team field (e.g. "modifiers.personsJoinMode") */
    field: string
    options: LemonRadioOption<T>[]
    defaultValue: T
    /** Optional callback after save */
    onSave?: (value: T) => void
}): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const currentTeamRecord = currentTeam as Record<string, any> | undefined

    // For modifier fields, check both modifiers and default_modifiers
    const savedValue = ((): T => {
        const parts = field.split('.')
        if (parts[0] === 'modifiers') {
            const modifierKey = parts.slice(1).join('.')
            return (
                getNestedValue(currentTeam?.modifiers, modifierKey) ??
                getNestedValue(currentTeam?.default_modifiers, modifierKey) ??
                defaultValue
            )
        }
        return (getNestedValue(currentTeamRecord, field) as T) ?? defaultValue
    })()

    const [value, setValue] = useState<T>(savedValue)
    useEffect(() => {
        setValue(savedValue)
    }, [savedValue])

    const handleSave = (): void => {
        const update = buildNestedUpdate(field, value, currentTeamRecord)
        updateCurrentTeam(update as Partial<TeamType>)
        onSave?.(value)
    }

    return (
        <>
            <LemonRadio value={value} onChange={setValue} options={options} />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={handleSave}
                    disabledReason={value === savedValue ? 'No changes to save' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
