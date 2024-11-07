import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { themeLogic, THEMES } from '~/layout/navigation-3000/themeLogic'

export const scene: SceneExport = {
    component: ThemeLibraryScene,
}

export function ThemeLibraryScene(): JSX.Element {
    const { customThemeId } = useValues(themeLogic)
    const { setCustomThemeId } = useActions(themeLogic)

    return (
        <div className="grid grid-cols-2 gap-4">
            <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.themeCreator()}>
                        Create
                    </LemonButton>
                }
            />
            {THEMES.map(({ id, title, primaryColors }) => (
                <LemonButton type="primary" key={id} onClick={() => setCustomThemeId(id)}>
                    <div className="w-full mt-[9.5px]">
                        <div className="h-64 overflow-hidden rounded">
                            <div className="flex relative h-[180%] w-[180%] top-[-40%] left-[-40%] rotate-12">
                                <div
                                    className="h-full w-1/3"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ background: primaryColors[0] }}
                                />
                                <div
                                    className="h-full w-1/3"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ background: primaryColors[1] }}
                                />
                                <div
                                    className="h-full w-1/3"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ background: primaryColors[2] }}
                                />
                            </div>
                        </div>
                        <div className="p-3 space-x-1">
                            <span className="font-semibold">{title}</span>
                            {id === customThemeId && <LemonTag>Selected</LemonTag>}
                        </div>
                    </div>
                </LemonButton>
            ))}
        </div>
    )
}
