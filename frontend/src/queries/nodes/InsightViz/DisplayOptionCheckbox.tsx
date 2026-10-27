import { useId } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, Tooltip } from '@posthog/lemon-ui'
import { Checkbox, FieldLabel } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillDisplayOptionInfo } from './QuillDisplayOptionInfo'
import { QuillDisplayOptionRow } from './QuillDisplayOptionRow'

export interface DisplayOptionCheckboxProps {
    label: string
    info?: string
    checked: boolean
    onChange: (checked: boolean) => void
    disabledReason?: string | null
}

export function DisplayOptionCheckbox({
    label,
    info,
    checked,
    onChange,
    disabledReason,
}: DisplayOptionCheckboxProps): JSX.Element {
    const id = useId()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillDisplayOptionRow disabledReason={disabledReason}>
                <Checkbox
                    id={id}
                    checked={checked}
                    onCheckedChange={(value: boolean) => onChange(value)}
                    disabled={!!disabledReason}
                />
                <FieldLabel htmlFor={id} className="font-normal">
                    {label}
                </FieldLabel>
                {info && <QuillDisplayOptionInfo info={info} />}
            </QuillDisplayOptionRow>
        )
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={checked}
            onChange={onChange}
            disabledReason={disabledReason}
            label={
                <span className="font-normal">
                    {label}
                    {info && (
                        <>
                            {' '}
                            <Tooltip title={info}>
                                <IconInfo className="relative top-0.5 text-lg text-secondary" />
                            </Tooltip>
                        </>
                    )}
                </span>
            }
            size="small"
        />
    )
}
