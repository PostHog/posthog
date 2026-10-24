export type TestAccountFilterChoice = 'inherit' | 'filter-out' | 'include'

export const TEST_ACCOUNT_CHOICE_TO_FILTER: Record<TestAccountFilterChoice, boolean | null> = {
    inherit: null,
    'filter-out': true,
    include: false,
}

export const TEST_ACCOUNT_CHOICE_HINTS: Record<TestAccountFilterChoice, string> = {
    inherit: 'Each insight keeps its own "Filter out internal and test users" setting.',
    'filter-out': 'Internal and test users are filtered out of every insight on this dashboard.',
    include: 'Internal and test users are included in every insight on this dashboard.',
}

export function testAccountFilterChoice(filterTestAccounts: boolean | null | undefined): TestAccountFilterChoice {
    return filterTestAccounts == null ? 'inherit' : filterTestAccounts ? 'filter-out' : 'include'
}
