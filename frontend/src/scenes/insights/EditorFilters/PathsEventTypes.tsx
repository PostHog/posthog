import { useActions, useValues } from 'kea'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { capitalizeFirstLetter } from 'lib/utils'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

import { EditorFilterProps, PathsFilterType, PathType } from '~/types'

import { humanizePathsEventTypes } from '../utils'

export function PathsEventsTypes({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(pathsDataLogic(insightProps))

    const includeEventTypes = pathsFilter?.include_event_types
    const setIncludeEventTypes = (includeEventTypes: PathsFilterType['include_event_types']): void => {
        updateInsightFilter({ include_event_types: includeEventTypes })
    }

    const options = [
        {
            type: PathType.PageView,
            label: 'Page views',
            selected: includeEventTypes?.includes(PathType.PageView),
        },
        {
            type: PathType.Screen,
            label: 'Screen views',
            selected: includeEventTypes?.includes(PathType.Screen),
        },
        {
            type: PathType.CustomEvent,
            label: 'Custom event',
            selected: includeEventTypes?.includes(PathType.CustomEvent),
        },
        {
            type: PathType.HogQL,
            label: 'HogQL expression',
            selected: includeEventTypes?.includes(PathType.HogQL),
        },
    ]

    const onClickPathtype = (pathType: PathType): void => {
        if (includeEventTypes) {
            if (includeEventTypes.includes(pathType)) {
                setIncludeEventTypes(includeEventTypes.filter((types) => types !== pathType))
            } else {
                setIncludeEventTypes(includeEventTypes ? [...includeEventTypes, pathType] : [pathType])
            }
        } else {
            setIncludeEventTypes([pathType])
        }
    }

    const summary = capitalizeFirstLetter(humanizePathsEventTypes(includeEventTypes).join(' & '))

    return (
        <LemonButtonWithDropdown
            status="stealth"
            fullWidth
            type="secondary"
            dropdown={{
                sameWidth: true,
                closeOnClickInside: false,
                overlay: options.map((option) => (
                    <LemonButton
                        key={option.type}
                        onClick={() => onClickPathtype(option.type)}
                        status="stealth"
                        disabledReason={
                            option.selected && includeEventTypes?.length === 1
                                ? 'At least one event type must be selected'
                                : undefined
                        }
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
        </LemonButtonWithDropdown>
    )
}
