import { LemonSelect, LemonSelectOptions, LemonSwitch } from '@posthog/lemon-ui'

export interface OnboardingProductConfigurationOptionProps {
    teamProperty: string
    title: string
    description?: string
    type: 'toggle' | 'select'
    selectOptions?: LemonSelectOptions<any>
    value: boolean | string | number | null
    onChange: (newValue: boolean | string | number) => void
}

export function OnboardingProductConfigurationOption({
    teamProperty,
    title,
    description,
    type,
    selectOptions,
    value,
    onChange,
}: OnboardingProductConfigurationOptionProps): JSX.Element {
    const controlId = `onboarding-config-${teamProperty}`

    return (
        <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2">
                <label htmlFor={controlId} className="text-base font-semibold cursor-pointer">
                    {title}
                </label>
                <p className="mt-2 mb-0 prompt-text">{description}</p>
            </div>
            <div className="flex justify-end">
                {type === 'toggle' ? (
                    <LemonSwitch
                        id={controlId}
                        data-attr={controlId}
                        onChange={onChange}
                        className="justify-end"
                        fullWidth={true}
                        checked={(value as boolean) || false}
                    />
                ) : (
                    <div className="flex gap-x-4 justify-end items-center mb-1">
                        <LemonSelect
                            id={controlId}
                            data-attr={controlId}
                            dropdownMatchSelectWidth={false}
                            onChange={onChange}
                            options={selectOptions || []}
                            value={value as string | number}
                        />
                    </div>
                )}
            </div>
        </div>
    )
}
