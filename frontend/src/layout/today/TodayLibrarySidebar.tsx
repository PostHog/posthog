import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconFolder } from '@posthog/icons'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { LibraryCreateButton } from 'scenes/library/LibraryCreateButton'
import { libraryLogic } from 'scenes/library/libraryLogic'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayPane } from './TodayPane'
import { TodayPaneGroup } from './TodayPaneGroup'
import { TodayPaneRow } from './TodayPaneRow'

/** The Library sub-nav: every saved object type, each opening a filtered list in the main area. */
export function TodayLibrarySidebar(): JSX.Element {
    const { objectTypes } = useValues(libraryLogic)
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)

    return (
        <TodayPane label="Library">
            <TodayPaneGroup label="Library">
                <TodayPaneRow
                    label="All objects"
                    icon={<IconFolder />}
                    to={urls.library()}
                    active={path === urls.library()}
                    dataAttr="today-library-all"
                />
                {objectTypes.map((type) => (
                    <TodayPaneRow
                        key={type.value}
                        label={type.pluralLabel}
                        icon={iconForType(type.value as FileSystemIconType)}
                        to={urls.library(type.value)}
                        active={path === urls.library(type.value)}
                        action={<LibraryCreateButton objectType={type.value} />}
                        dataAttr="today-library-type"
                    />
                ))}
            </TodayPaneGroup>
        </TodayPane>
    )
}
