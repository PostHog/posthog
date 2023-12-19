import { IconDay, IconLaptop, IconNight } from '@posthog/icons'
import { LemonSelect, LemonSelectProps } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export function ThemeSwitcher({
    onlyLabel,
    ...props
}: Partial<LemonSelectProps<any>> & { onlyLabel?: boolean }): JSX.Element {
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

    return (
        <LemonSelect
            options={[
                { icon: <IconLaptop />, value: null, label: `Sync with system` },
                { icon: <IconDay />, value: 'light', label: 'Light mode' },
                { icon: <IconNight />, value: 'dark', label: 'Dark mode' },
            ]}
            value={user?.theme_mode}
            renderButtonContent={(leaf) => {
                const labelText = leaf ? leaf.label : 'Sync with system'
                return onlyLabel ? (
                    labelText
                ) : (
                    <>
                        <span className="flex-1 flex justify-between items-baseline gap-4">
                            <span>Color theme</span>
                            <span className="font-normal text-xs">{leaf ? leaf.label : 'Sync with system'}</span>
                        </span>
                    </>
                )
            }}
            onChange={(value) => updateUser({ theme_mode: value })}
            dropdownPlacement="right-start"
            dropdownMatchSelectWidth={false}
            {...props}
        />
    )
}
