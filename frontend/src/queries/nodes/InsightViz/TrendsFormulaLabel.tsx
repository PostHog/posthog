import { useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { QueryEditorFilterProps } from '~/types'

export function TrendsFormulaLabel({ insightProps }: QueryEditorFilterProps): JSX.Element | null {
    const { isFormulaOn } = useValues(trendsLogic(insightProps))
    return isFormulaOn ? <>Formula</> : null
}
