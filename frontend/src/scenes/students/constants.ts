// Client-side sanity check only. The billing service owns the authoritative academic-domain
// check, so this stays permissive: .edu, .edu.<cc> (edu.au, edu.cn, ...) and .ac.<cc> (ac.uk, ac.jp, ...).
export const ACADEMIC_EMAIL_DOMAIN_REGEX = /\.(edu|ac)(\.[a-z]{2})?$/i
