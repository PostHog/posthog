import { useValues, useActions } from 'kea'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { PathType, EditorFilterProps, QueryEditorFilterProps, PathsFilterType } from '~/types'
import { LemonButtonWithPopup, LemonButton } from 'lib/components/LemonButton'
import { humanizePathsEventTypes } from '../utils'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { capitalizeFirstLetter } from 'lib/utils'
import { pathsDataLogic } from 'scenes/paths/pathsDataLogic'

export function PathsEventsTypesDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { includeEventTypes } = useValues(pathsDataLogic(insightProps))
    const { setIncludeEventTypes } = useActions(pathsDataLogic(insightProps))

    return (
        <PathsEventTypesComponent includeEventTypes={includeEventTypes} setIncludeEventTypes={setIncludeEventTypes} />
    )
}

export function PathsEventTypes({ insightProps }: EditorFilterProps): JSX.Element {
    const { filter } = useValues(pathsLogic(insightProps))
    const { setFilter } = useActions(pathsLogic(insightProps))

    return (
        <PathsEventTypesComponent
            includeEventTypes={filter.include_event_types}
            setIncludeEventTypes={(includeEventTypes: PathsFilterType['include_event_types']) => {
                setFilter({
                    include_event_types: includeEventTypes,
                })
            }}
        />
    )
}

type PathsEventTypesComponentProps = {
    includeEventTypes: PathsFilterType['include_event_types']
    setIncludeEventTypes: (includeEventTypes: PathsFilterType['include_event_types']) => void
}

export function PathsEventTypesComponent({
    includeEventTypes,
    setIncludeEventTypes,
}: PathsEventTypesComponentProps): JSX.Element {
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
            label: 'Custom events',
            selected: includeEventTypes?.includes(PathType.CustomEvent),
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
                        disabled={option.selected && includeEventTypes?.length === 1}
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
