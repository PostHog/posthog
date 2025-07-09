import {
    getPanelDimensions,
    calculateCSSPosition,
    getFloatingMaxDimensions,
    calculateSnapPosition,
} from './floatingMaxPositioning'

// Mock DOM elements and methods
const mockGetBoundingClientRect = jest.fn()
const mockGetComputedStyle = jest.fn()

// Setup DOM mocks
beforeEach(() => {
    // Reset mocks
    mockGetBoundingClientRect.mockReset()
    mockGetComputedStyle.mockReset()

    // Mock getElementById
    const mockElements: Record<string, any> = {
        'side-panel': { getBoundingClientRect: mockGetBoundingClientRect },
        'project-panel-layout': { getBoundingClientRect: mockGetBoundingClientRect },
        'floating-max': { getBoundingClientRect: mockGetBoundingClientRect },
    }

    jest.spyOn(document, 'getElementById').mockImplementation((id: string) => mockElements[id] || null)
    jest.spyOn(document, 'querySelector').mockImplementation(
        () =>
            ({
                style: { marginBottom: '6px', paddingBottom: '0px', borderBottomWidth: '0px' },
            } as any)
    )

    // Mock getElementsByClassName for getCSSVariableValue
    jest.spyOn(document, 'getElementsByClassName').mockImplementation((className: string) => {
        if (className === 'Navigation3000') {
            return [{} as Element] as any
        }
        return [] as any
    })

    // Mock getComputedStyle
    global.getComputedStyle = mockGetComputedStyle.mockReturnValue({
        marginBottom: '6px',
        paddingBottom: '0px',
        borderBottomWidth: '0px',
        getPropertyValue: (prop: string) => {
            if (prop === '--scene-padding') {
                return '16px'
            }
            return ''
        },
    })

    // Mock window dimensions
    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true })
    Object.defineProperty(window, 'innerHeight', { value: 768, writable: true })

    // Mock touch detection
    Object.defineProperty(window, 'ontouchstart', { value: undefined, writable: true })
    Object.defineProperty(navigator, 'maxTouchPoints', { value: 0, writable: true })
})

afterEach(() => {
    jest.restoreAllMocks()
})

describe('getPanelDimensions', () => {
    it('should return panel dimensions with side and project panel widths', () => {
        mockGetBoundingClientRect.mockReturnValueOnce({ width: 240 }) // side panel
        mockGetBoundingClientRect.mockReturnValueOnce({ width: 320 }) // project panel

        const result = getPanelDimensions()

        expect(result).toEqual({
            sidePanelWidth: 240,
            projectPanelWidth: 320,
            xPadding: 16,
        })
    })

    it('should return 0 when panels do not exist', () => {
        jest.spyOn(document, 'getElementById').mockReturnValue(null)

        const result = getPanelDimensions()

        expect(result).toEqual({
            sidePanelWidth: 0,
            projectPanelWidth: 0,
            xPadding: 16,
        })
    })
})

describe('calculateCSSPosition', () => {
    beforeEach(() => {
        mockGetBoundingClientRect.mockReturnValueOnce({ width: 240 }) // side panel
        mockGetBoundingClientRect.mockReturnValueOnce({ width: 320 }) // project panel
    })

    it('should calculate left position correctly', () => {
        const result = calculateCSSPosition('left')

        expect(result).toEqual({
            left: '340px', // 320 + 16 + 4
        })
    })

    it('should calculate right position correctly', () => {
        const result = calculateCSSPosition('right')

        expect(result).toEqual({
            right: '260px', // 240 + 16 + 4
        })
    })
})

describe('getFloatingMaxDimensions', () => {
    it('should return floating max dimensions', () => {
        mockGetBoundingClientRect.mockReturnValue({ width: 48, height: 48 })

        const result = getFloatingMaxDimensions()

        expect(result).toEqual({
            width: 48,
            height: 48,
        })
    })

    it('should return 0 dimensions when element does not exist', () => {
        jest.spyOn(document, 'getElementById').mockReturnValue(null)

        const result = getFloatingMaxDimensions()

        expect(result).toEqual({
            width: 0,
            height: 0,
        })
    })
})

describe('calculateSnapPosition', () => {
    beforeEach(() => {
        mockGetBoundingClientRect.mockReturnValueOnce({ width: 240 }) // side panel
        mockGetBoundingClientRect.mockReturnValueOnce({ width: 320 }) // project panel
    })

    it('should snap to left side when mouse is on left half', () => {
        const result = calculateSnapPosition(400, 6, 48) // mouseX < 512 (half of 1024)

        expect(result).toEqual({
            x: 340, // 320 + 16 + 4
            y: 714, // 768 - 48 - 6
            side: 'left',
        })
    })

    it('should snap to right side when mouse is on right half', () => {
        const result = calculateSnapPosition(600, 6, 48) // mouseX > 512 (half of 1024)

        expect(result).toEqual({
            x: 716, // 1024 - 240 - 16 - 4 - 48 (corrected calculation)
            y: 714, // 768 - 48 - 6
            side: 'right',
        })
    })

    it('should work with default avatar width', () => {
        const result = calculateSnapPosition(400, 6)

        expect(result).toEqual({
            x: 340,
            y: 762, // 768 - 0 - 6
            side: 'left',
        })
    })
})
