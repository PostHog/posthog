// The quickstart-homepage experiment arms that get Quickstart as the post-onboarding
// destination. 'test' is the full page; 'test2' cuts everything below the product cards.
export function isQuickstartHomepageEnabled(variant: string | boolean | undefined): boolean {
    return variant === 'test' || variant === 'test2'
}
