// PostHog brand colors
export const colors = {
  // Primary brand
  orange: '#F54E00',
  yellow: '#F9BD2B',
  blue: '#1D4AFF',

  // UI colors
  darkBg: '#1D1F27',
  lightBg: '#2C2F3E',
  border: '#4A4F5E',

  // Text colors
  text: '#FFFFFF',
  textMuted: '#9CA3AF',
  textDim: '#6B7280',

  // Status colors
  success: '#22C55E',
  error: '#EF4444',
  warning: '#F59E0B',
  info: '#3B82F6',

  // Event type colors (for variety in the table)
  eventColors: [
    '#F54E00', // orange
    '#1D4AFF', // blue
    '#22C55E', // green
    '#A855F7', // purple
    '#06B6D4', // cyan
    '#F59E0B', // amber
    '#EC4899', // pink
    '#8B5CF6', // violet
  ],
}

// Get a consistent color for an event type
export const getEventColor = (eventType: string): string => {
  let hash = 0
  for (let i = 0; i < eventType.length; i++) {
    hash = ((hash << 5) - hash) + eventType.charCodeAt(i)
    hash = hash & hash
  }
  return colors.eventColors[Math.abs(hash) % colors.eventColors.length]
}
