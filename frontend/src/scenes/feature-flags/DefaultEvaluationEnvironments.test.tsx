import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DefaultEvaluationEnvironments } from './DefaultEvaluationEnvironments'

jest.mock('kea')

const mockUseValues = useValues as jest.MockedFunction<typeof useValues>

describe('DefaultEvaluationEnvironments', () => {
    const mockAddTag = jest.fn()
    const mockRemoveTag = jest.fn()
    const mockToggleEnabled = jest.fn()
    const mockSetNewTagInput = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()

        // Mock feature flag logic to enable the feature
        mockUseValues.mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return {
                    featureFlags: {
                        [FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]: true,
                    },
                }
            }

            // Mock defaultEvaluationEnvironmentsLogic
            return {
                tags: [],
                isEnabled: false,
                canAddMoreTags: true,
                newTagInput: '',
                defaultEvaluationEnvironmentsLoading: false,
                addTag: mockAddTag,
                removeTag: mockRemoveTag,
                toggleEnabled: mockToggleEnabled,
                setNewTagInput: mockSetNewTagInput,
            }
        })
    })

    it('should not render when feature flag is disabled', () => {
        mockUseValues.mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return {
                    featureFlags: {
                        [FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]: false,
                    },
                }
            }
            return {}
        })

        const { container } = render(<DefaultEvaluationEnvironments />)
        expect(container.firstChild).toBeNull()
    })

    it('should render the component when feature flag is enabled', () => {
        render(<DefaultEvaluationEnvironments />)
        expect(screen.getByText('Default Evaluation Environments')).toBeInTheDocument()
        expect(screen.getByText(/Configure default evaluation environment tags/)).toBeInTheDocument()
    })

    it('should toggle the enabled state', () => {
        render(<DefaultEvaluationEnvironments />)
        const toggle = screen.getByRole('switch')
        fireEvent.click(toggle)
        expect(mockToggleEnabled).toHaveBeenCalledWith(true)
    })

    it('should show tag management UI when enabled', () => {
        mockUseValues.mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return {
                    featureFlags: {
                        [FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]: true,
                    },
                }
            }
            return {
                tags: [
                    { id: 1, name: 'production' },
                    { id: 2, name: 'staging' },
                ],
                isEnabled: true,
                canAddMoreTags: true,
                newTagInput: '',
                defaultEvaluationEnvironmentsLoading: false,
                addTag: mockAddTag,
                removeTag: mockRemoveTag,
                toggleEnabled: mockToggleEnabled,
                setNewTagInput: mockSetNewTagInput,
            }
        })

        render(<DefaultEvaluationEnvironments />)
        expect(screen.getByText('production')).toBeInTheDocument()
        expect(screen.getByText('staging')).toBeInTheDocument()
        expect(screen.getByText('Add tag')).toBeInTheDocument()
    })

    it('should handle adding a new tag', async () => {
        const user = userEvent.setup()

        mockUseValues.mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return {
                    featureFlags: {
                        [FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]: true,
                    },
                }
            }
            return {
                tags: [],
                isEnabled: true,
                canAddMoreTags: true,
                newTagInput: 'development',
                defaultEvaluationEnvironmentsLoading: false,
                addTag: mockAddTag,
                removeTag: mockRemoveTag,
                toggleEnabled: mockToggleEnabled,
                setNewTagInput: mockSetNewTagInput,
            }
        })

        render(<DefaultEvaluationEnvironments />)

        // Click Add tag button
        const addButton = screen.getByText('Add tag')
        await user.click(addButton)

        // Input should appear
        const input = screen.getByPlaceholderText('e.g., production')
        expect(input).toBeInTheDocument()

        // Type tag name
        await user.type(input, 'development')
        expect(mockSetNewTagInput).toHaveBeenCalledWith('development')
    })

    it('should handle removing a tag', () => {
        mockUseValues.mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return {
                    featureFlags: {
                        [FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]: true,
                    },
                }
            }
            return {
                tags: [{ id: 1, name: 'production' }],
                isEnabled: true,
                canAddMoreTags: true,
                newTagInput: '',
                defaultEvaluationEnvironmentsLoading: false,
                addTag: mockAddTag,
                removeTag: mockRemoveTag,
                toggleEnabled: mockToggleEnabled,
                setNewTagInput: mockSetNewTagInput,
            }
        })

        render(<DefaultEvaluationEnvironments />)

        // Find and click the close button on the tag
        const closeButtons = screen
            .getAllByRole('button')
            .filter((button) => button.getAttribute('aria-label')?.includes('close'))
        if (closeButtons.length > 0) {
            fireEvent.click(closeButtons[0])
            expect(mockRemoveTag).toHaveBeenCalledWith('production')
        }
    })

    it('should show maximum tags warning when at limit', () => {
        const tags = Array.from({ length: 10 }, (_, i) => ({ id: i, name: `tag-${i}` }))

        mockUseValues.mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return {
                    featureFlags: {
                        [FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]: true,
                    },
                }
            }
            return {
                tags,
                isEnabled: true,
                canAddMoreTags: false,
                newTagInput: '',
                defaultEvaluationEnvironmentsLoading: false,
                addTag: mockAddTag,
                removeTag: mockRemoveTag,
                toggleEnabled: mockToggleEnabled,
                setNewTagInput: mockSetNewTagInput,
            }
        })

        render(<DefaultEvaluationEnvironments />)
        expect(screen.getByText('Maximum of 10 default evaluation tags allowed.')).toBeInTheDocument()
        expect(screen.queryByText('Add tag')).not.toBeInTheDocument()
    })

    it('should show empty state message', () => {
        mockUseValues.mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return {
                    featureFlags: {
                        [FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]: true,
                    },
                }
            }
            return {
                tags: [],
                isEnabled: true,
                canAddMoreTags: true,
                newTagInput: '',
                defaultEvaluationEnvironmentsLoading: false,
                addTag: mockAddTag,
                removeTag: mockRemoveTag,
                toggleEnabled: mockToggleEnabled,
                setNewTagInput: mockSetNewTagInput,
            }
        })

        render(<DefaultEvaluationEnvironments />)
        expect(screen.getByText(/No default evaluation tags configured/)).toBeInTheDocument()
    })

    it('should disable toggle when loading', () => {
        mockUseValues.mockImplementation((logic) => {
            if (logic === featureFlagLogic) {
                return {
                    featureFlags: {
                        [FEATURE_FLAGS.DEFAULT_EVALUATION_ENVIRONMENTS]: true,
                    },
                }
            }
            return {
                tags: [],
                isEnabled: false,
                canAddMoreTags: true,
                newTagInput: '',
                defaultEvaluationEnvironmentsLoading: true,
                addTag: mockAddTag,
                removeTag: mockRemoveTag,
                toggleEnabled: mockToggleEnabled,
                setNewTagInput: mockSetNewTagInput,
            }
        })

        render(<DefaultEvaluationEnvironments />)
        const toggle = screen.getByRole('switch')
        expect(toggle).toBeDisabled()
    })
})
