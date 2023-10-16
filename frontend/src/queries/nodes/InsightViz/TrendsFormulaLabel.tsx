import { useValues } from 'kea'
import { insightVizLogic } from 'scenes/insights/insightVizLogic'
import { EditorFilterProps } from '~/types'

export function TrendsFormulaLabel({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { hasFormula } = useValues(insightVizLogic(insightProps))
    return hasFormula ? <>Formula</> : null
}
