Feature: Trends page

    Scenario: Click an action
        Given we are on trends page
        When we click an action
        Then the line graph should exist
    
    Scenario: Add overall filter to default
        Given we are on trends page
        When we add a filter
        Then the line graph should exist
    
    Scenario: Add overall filter with added action
        Given we are on trends page
        When we click an action
        When we add a filter
        Then the line graph should exist