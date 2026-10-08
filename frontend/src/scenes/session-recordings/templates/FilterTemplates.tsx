import { RecordingUniversalFilters, ReplayTemplateCategory } from '~/types'

import { replayTemplates } from './availableTemplates'
import { FilterTemplateCard } from './FilterTemplateCard'
import { ReplayTemplateUsedSource } from './sessionRecordingTemplatesLogic'

const allCategories: ReplayTemplateCategory[] = replayTemplates
    .flatMap((template) => template.categories)
    .filter((category, index, self) => self.indexOf(category) === index)

export function FilterTemplates({
    source,
    onApply,
}: {
    source: ReplayTemplateUsedSource
    onApply: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-6">
            {allCategories.map((category) => (
                <div key={category} className="flex flex-col gap-2">
                    <h3 className="mb-0">{category}</h3>
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(24rem,1fr))] gap-3 items-start">
                        {replayTemplates
                            .filter((template) => template.categories.includes(category))
                            .map((template) => (
                                <FilterTemplateCard
                                    key={template.key}
                                    template={template}
                                    category={category}
                                    source={source}
                                    onApply={onApply}
                                />
                            ))}
                    </div>
                </div>
            ))}
        </div>
    )
}
