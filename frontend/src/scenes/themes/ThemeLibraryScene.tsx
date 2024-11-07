import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { themeLogic, THEMES } from '~/layout/navigation-3000/themeLogic'

export const scene: SceneExport = {
    component: ThemeLibraryScene,
}

export function ThemeLibraryScene(): JSX.Element {
    const { customThemeId } = useValues(themeLogic)
    const { setCustomThemeId } = useActions(themeLogic)
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <div className="grid grid-cols-2 gap-4">
            {/* <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.themeCreator()}>
                        Create
                    </LemonButton>
                }
            /> */}
            <ThemeCard
                title="Light"
                color0="#f3f4ef"
                color1="#f3f4ef"
                color2="#f3f4ef"
                selected={customThemeId === null && user?.theme_mode === 'light'}
                onClick={() => {
                    updateUser({ theme_mode: 'light' })
                    setCustomThemeId(null)
                }}
            />
            <ThemeCard
                title="Dark"
                color0="#1d1f27"
                color1="#1d1f27"
                color2="#1d1f27"
                selected={customThemeId === null && user?.theme_mode === 'dark'}
                onClick={() => {
                    updateUser({ theme_mode: 'dark' })
                    setCustomThemeId(null)
                }}
            />
            {THEMES.map(({ id, title, primaryColors, baseTheme, disabled }) => (
                <ThemeCard
                    key={id}
                    title={title}
                    color0={primaryColors[0]}
                    color1={primaryColors[1]}
                    color2={primaryColors[2]}
                    disabled={disabled}
                    selected={id === customThemeId}
                    onClick={() => {
                        updateUser({ theme_mode: baseTheme })
                        setCustomThemeId(id)
                    }}
                />
            ))}
        </div>
    )
}

const ThemeCard = ({
    title,
    color0,
    color1,
    color2,
    selected,
    disabled = false,
    onClick,
}: {
    title: string
    color0: string
    color1: string
    color2: string
    selected: boolean
    disabled?: boolean
    onClick: () => void
}): JSX.Element => {
    return (
        <LemonButton type="primary" onClick={onClick} disabledReason={disabled ? 'Coming soon' : undefined}>
            <div className="w-full mt-[9.5px]">
                <div className="h-64 overflow-hidden rounded">
                    <div className="flex relative h-[180%] w-[180%] top-[-40%] left-[-40%] rotate-12">
                        <div
                            className="h-full w-1/3"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ background: color0 }}
                        />
                        <div
                            className="h-full w-1/3"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ background: color1 }}
                        />
                        <div
                            className="h-full w-1/3"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ background: color2 }}
                        />
                    </div>
                </div>
                <div className="p-3 space-x-1">
                    <span className="font-semibold">{title}</span>
                    {selected && <LemonTag type="option">Selected</LemonTag>}
                </div>
            </div>
        </LemonButton>
    )
}
