export const PLATFORM_TYPE = 'PLATFORM_TYPE'
export const AUTOCAPTURE = 'AUTOCAPTURE'
export const FRAMEWORK = 'FRAMEWORK'
export const INSTRUCTIONS = 'INSTRUCTIONS'
export const VERIFICATION = 'VERIFICATION'

export const WEB = 'Web'
export const MOBILE = 'Mobile'
export const BACKEND = 'Backend'
export const platforms = [WEB, MOBILE, BACKEND]

export const PURE_JS = 'PURE_JS'
export const NODEJS = 'NODEJS'
export const GO = 'GO'
export const RUBY = 'RUBY'
export const PYTHON = 'PYTHON'
export const PHP = 'PHP'
export const ELIXIR = 'ELIXIR'
export const API = 'API'

export const ANDROID = 'ANDROID'
export const IOS = 'IOS'
export const REACT_NATIVE = 'REACT_NATIVE'
export const FLUTTER = 'FLUTTER'

export const webFrameworks = {
    [NODEJS]: 'Node.js',
    [GO]: 'Go',
    [RUBY]: 'Ruby',
    [PYTHON]: 'Python',
    [PHP]: 'PHP',
    [ELIXIR]: 'Elixir',
}

export const mobileFrameworks = {
    [ANDROID]: 'Android',
    [IOS]: 'iOS',
    [REACT_NATIVE]: 'React Native',
    [FLUTTER]: 'Flutter',
}
