import {
    IconBolt,
    IconBuilding,
    IconClock,
    IconCode,
    IconCursorClick,
    IconPeople,
    IconPerson,
    IconList,
    IconToggle,
} from '@posthog/icons'

import { registeredFilterBarCategory } from './filterBarCategories'
import { FilterBarCategoryId } from './filterBarTypes'

/** The glyph that stands for a category in the picker rows and on the chip of every filter from it. */
export function FilterBarCategoryIcon({
    categoryId,
    className,
}: {
    categoryId: FilterBarCategoryId
    className?: string
}): JSX.Element {
    const RegisteredIcon = registeredFilterBarCategory(categoryId)?.icon
    if (RegisteredIcon) {
        return <RegisteredIcon className={className} />
    }
    if (categoryId.startsWith('group_properties_')) {
        return <IconBuilding className={className} />
    }
    switch (categoryId) {
        case 'event_properties':
            return <IconList className={className} />
        case 'person_properties':
            return <IconPerson className={className} />
        case 'session_properties':
            return <IconClock className={className} />
        case 'feature_flags':
            return <IconToggle className={className} />
        case 'cohorts':
            return <IconPeople className={className} />
        case 'elements':
            return <IconCursorClick className={className} />
        case 'sql':
            return <IconCode className={className} />
        default:
            return <IconBolt className={className} />
    }
}
