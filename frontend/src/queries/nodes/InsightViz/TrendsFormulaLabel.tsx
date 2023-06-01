import { useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps } from '~/types'

export function TrendsFormulaLabel({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { isFormulaOn } = useValues(trendsLogic(insightProps))
    return isFormulaOn ? <>Formula</> : null
}
