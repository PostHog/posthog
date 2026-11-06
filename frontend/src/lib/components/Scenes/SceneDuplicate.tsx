import { IconCopy } from '@posthog/icons'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from './utils'

interface SceneDuplicateProps extends SceneDataAttrKeyProps {
    onClick: () => void
    loading?: boolean
}

export function SceneDuplicate({ dataAttrKey, onClick, loading }: SceneDuplicateProps): JSX.Element {
    return (
        <ButtonPrimitive
            menuItem
            onClick={onClick}
            disabled={loading}
            data-attr={`${dataAttrKey}-duplicate-button`}
            tooltip={loading ? 'Duplicating…' : 'Duplicate resource'}
        >
            {loading ? <Spinner textColored /> : <IconCopy />}
            Duplicate
        </ButtonPrimitive>
    )
}
