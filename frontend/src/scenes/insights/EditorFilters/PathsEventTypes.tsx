import React from 'react'
import { useValues, useActions } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { PathType, EditorFilterProps } from '~/types'
import { LemonButtonWithPopup, LemonButton } from 'lib/components/LemonButton'
import { humanizePathsEventTypes } from '../utils'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { capitalizeFirstLetter } from 'lib/utils'

export function PathsEventTypes({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    const options = [
        {
            type: PathType.PageView,
            label: 'Page views',
            selected: filter.include_event_types?.includes(PathType.PageView),
        },
        {
            type: PathType.Screen,
            label: 'Screen views',
            selected: filter.include_event_types?.includes(PathType.Screen),
        },
        {
            type: PathType.CustomEvent,
            label: 'Custom events',
            selected: filter.include_event_types?.includes(PathType.CustomEvent),
        },
    ]

    const onClickPathtype = (pathType: PathType): void => {
        if (filter.include_event_types) {
            if (filter.include_event_types.includes(pathType)) {
                setFilter({
                    include_event_types: filter.include_event_types.filter((types) => types !== pathType),
                })
            } else {
                setFilter({
                    include_event_types: filter.include_event_types
                        ? [...filter.include_event_types, pathType]
                        : [pathType],
                })
            }
        } else {
            setFilter({
                include_event_types: [pathType],
            })
        }
    }

    const summary = capitalizeFirstLetter(humanizePathsEventTypes(filter).join(' & '))

    return (
        <LemonButtonWithPopup
            status="stealth"
            fullWidth
            type="secondary"
            popup={{
                sameWidth: true,
                closeOnClickInside: false,
                overlay: options.map((option) => (
                    <LemonButton
                        key={option.type}
                        onClick={() => onClickPathtype(option.type)}
                        status="stealth"
                        disabled={option.selected && filter.include_event_types?.length === 1}
                        fullWidth
                        data-attr={option['data-attr']}
                    >
                        <span className="pointer-events-none mr-2">
                            <LemonCheckbox checked={option.selected} />
                        </span>
                        {option.label}
                    </LemonButton>
                )),
                actionable: true,
            }}
        >
            {summary}
        </LemonButtonWithPopup>
    )
}
