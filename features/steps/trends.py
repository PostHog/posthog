from behave import *
import time


@given('we are on trends page')
def step_impl(context):
    context.TrendsPage.open()

@when('we click an action')
def step_impl(context):
    context.TrendsPage.add_action_event_button.click()
    context.TrendsPage.select_action_dropdown.click()
    context.browser.find_by_text('Pageviews').first.click()

@when('we add a filter')
def step_impl(context):
    context.TrendsPage.filter_dropdown.click()
    time.sleep(0.5)
    context.browser.find_by_text('$current_url').first.click()
    time.sleep(0.5)
    context.TrendsPage.prop_val_dropdown.click()
    context.browser.find_by_text('http://localhost:8000/demo/1/').first.click()

@then('the line graph should exist')
def step_impl(context):
    time.sleep(1)
    assert context.TrendsPage.line_graph is not None