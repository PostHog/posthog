import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyPluginMeta } from '../../types'

export function processEvent(event: PluginEvent, _: LegacyPluginMeta) {
    switch (event.event) {
        case 'Community Management Dashboard Displayed':
        case 'Community Management Insights Overview Tab Displayed':
            event.event = 'Analytics Community Overview Tab Displayed'
            break
        case 'Community Management Insights Sociodemographic Tab Displayed':
            event.event = 'Analytics Community Sociodemographic Tab Displayed'
            break
        case 'Community Management Insights Purchase Behavior Tab Displayed':
            event.event = 'Analytics Community Purchase Behavior Tab Displayed'
            break
        case 'Community Management Insights Music Tastes Tab Displayed':
            event.event = 'Analytics Community Musical Tastes Tab Displayed'
            break
        case 'Community Management Contact Filter Button Tapped':
            event.event = 'Marketing Contacts Filters Button Tapped'
            break
        case 'Community Management Contact Filters Applied':
            event.event = 'Marketing Contacts Filters Applied'
            break
        case 'Community Management Contacts Exported':
            event.event = 'Marketing Contacts Exported'
            break
        case 'Community Management Contacts Imported':
            event.event = 'Marketing Contacts Imported'
            break
        case 'Community Management Contacts Tab Displayed':
            event.event = 'Marketing Contacts Tab Displayed'
            break
        case 'Community Management Segment CSV Export Button Tapped':
            event.event = 'Marketing Segment Exported'
            break
        case 'Community Management Segment Created':
            event.event = 'Marketing Segment Created'
            break
        case 'Community Management Segment Displayed':
            event.event = 'Marketing Segment Displayed'
            break
        case 'Community Management Segments List Displayed':
            event.event = 'Marketing Segments Tab Displayed'
            break
        case 'Community Management Organizer Page Form Displayed':
        case 'Marketing Organizer Page Tab Displayed':
        case 'Marketing Organizer Widget Tab Displayed':
            event.event = 'My Page Tab Displayed'
            break
        case 'Organizer Page Updated':
            event.event = 'My Page Edited'
            break
        case 'App Open':
            event.event = 'App Foregrounded'
            break
        case 'Open Website':
            event.event = 'Website Opened'
            break
        case 'Signup':
        case 'SignupGuest':
            event.event = 'Sign Up Completed'
            break
        case 'Log In':
            event.event = 'Log In Completed'
            break
        case 'Tap Areas':
            event.event = 'Home Screen Area Tapped'
            break
        case 'Switch Area':
            event.event = 'Area Switched'
            break
        case 'Search':
            event.event = 'Content Searched'
            break
        case 'Tap Event':
            event.event = 'Event Tapped'
            break
        case 'Event Page Viewed':
            event.event = 'Event Page Displayed'
            break
        case 'Organizer Page Viewed':
        case 'Organizer Screen Displayed':
            event.event = 'Organizer Page Displayed'
            break
        case 'Artist Page Viewed':
        case 'Artist Screen Displayed':
            event.event = 'Artist Page Displayed'
            break
        case 'Shotgun':
            event.event = 'Event Page Available Tickets Tapped'
            break
        case 'Event Screen Interest Button Tapped':
            event.event = 'Event Interest Activated'
            break
        case 'Event Screen Uninterest Button Tapped':
            event.event = 'Event Interest Deactivated'
            break
        case 'Share Event':
        case 'Send Event':
            event.event = 'Event Shared'
            break
        case 'Add Ticket To Basket':
            event.event = 'Basket Item Added'
            break
        case 'Tap Coupon':
            event.event = 'Basket Add Coupon Tapped'
            break
        case 'Add Coupon':
            event.event = 'Coupon Added'
            break
        case 'Remove Ticket From Basket':
            event.event = 'Basket Item Removed'
            break
        case 'Validate Basket':
        case 'Pressed Order':
            event.event = 'Basket Validated'
            break
        case 'Purchase':
            event.event = 'Payment Validated'
            break
        case 'Get Printed Tickets':
        case 'Download Ticket':
            event.event = 'Order Confirmation Download Tickets Button Tapped'
            break
        case 'Show User Event Tickets':
            event.event = 'Ticket List Screen Displayed'
            break
        case 'Resell Ticket':
            event.event = 'Ticket Screen Resell Tapped'
            break
        case 'WaitingListDisplayed':
            event.event = 'Waiting List Displayed'
            break
        case 'Transfer Ticket':
            event.event = 'Ticket Screen Transfer Tapped'
            break
        case 'Select Resell Mode':
            event.event = 'Resell Ticket Screen Mode Selected'
            break
        case 'Confirm Resell Ticket':
            event.event = 'Ticket Resell Validated'
            break
        case 'Select Receiver':
            event.event = 'Transfer Screen Receiver Selected'
            break
        case 'Tap Newsfeed':
            event.event = 'Notification Center Tapped'
            break
        case 'Tap Newsfeed Item':
            event.event = 'Notification Center Item Tapped'
            break
        case 'Tap Chloe':
        case 'Help Tapped':
            event.event = 'Contact Support Clicked'
            break
        case 'Help CTA Clicked':
            event.event = 'Contact Support Clicked'
            break
        case 'Music Library Sync BottomSheet Displayed':
            event.event = 'Music Library Sync Form Displayed'
            break
        case 'Music Library Sync Streaming Account Tapped':
            event.event = 'Music Library Sync Form Sync Button Tapped'
            break
        case 'Music Library Sync Success':
            event.event = 'Music Library Sync Completed'
            break
        case 'Settings':
        case 'Settings Screen Displayed':
            event.event = 'Profile Screen Settings Tapped'
            break
        case 'Tap Score':
            event.event = 'Profile Screen Score Tapped'
            break
        case 'Add Payment Solution':
            event.event = 'Payment Methods Screen Add Method Tapped'
            break
        case 'Log Out':
            event.event = 'Logged Out'
            break
        default:
            break
    }

    return event
}
