import { useValues } from 'kea'

import { LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { cloudAgentsCatalogLogic } from '../logics/cloudAgentsCatalogLogic'

export function ModelSelect({
    value,
    onChange,
    'data-attr': dataAttr,
}: {
    value: string | null
    onChange: (model: string | null) => void
    'data-attr'?: string
}): JSX.Element {
    const { models, catalogLoading } = useValues(cloudAgentsCatalogLogic)
    const defaultModel = models.find((model) => model.is_default)
    const options: LemonSelectOption<string | null>[] = [
        { value: null, label: defaultModel ? `Default (${defaultModel.name})` : 'Default model' },
        ...models.map((model) => ({ value: model.id, label: model.name })),
    ]
    return (
        <LemonSelect
            fullWidth
            value={value}
            onChange={onChange}
            options={options}
            loading={catalogLoading}
            data-attr={dataAttr}
        />
    )
}
