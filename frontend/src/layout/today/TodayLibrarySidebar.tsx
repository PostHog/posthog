import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconFolder } from '@posthog/icons'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayCreateObjectButton } from './TodayCreateObjectButton'
import { libraryUrl, todayLibraryLogic } from './todayLibraryLogic'
import { TodayPaneRow } from './TodayPaneRow'
import { railPaneForPath } from './todayShellLogic'

/** The Library sub-nav: every saved object type, each opening a filtered list in the main area. */
export function TodayLibrarySidebar(): JSX.Element {
    const { objectTypes, objectType } = useValues(todayLibraryLogic)
    const { location } = useValues(router)
    const onLibrary = railPaneForPath(location.pathname, location.search) === 'library'

    return (
        <div className="TodayPane">
            <div className="TodayPane__scroll">
                <div className="TodayPane__heading Today__label">Library</div>
                <TodayPaneRow
                    label="All objects"
                    icon={<IconFolder />}
                    to={libraryUrl()}
                    active={onLibrary && !objectType}
                    dataAttr="today-library-all"
                />
                {objectTypes.map((type) => (
                    <TodayPaneRow
                        key={type.value}
                        label={type.pluralLabel}
                        icon={iconForType(type.value as FileSystemIconType)}
                        to={libraryUrl(type.value)}
                        active={onLibrary && objectType === type.value}
                        action={<TodayCreateObjectButton objectType={type.value} />}
                        dataAttr="today-library-type"
                    />
                ))}
            </div>
        </div>
    )
}
