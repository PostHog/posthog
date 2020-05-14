from splinter import Browser
from features.pages.trends import TrendsPage

# behave hook
def before_all(context):
    base_url = 'http://localhost:8000'

    context.browser = Browser('chrome', headless=True)
    context.TrendsPage = TrendsPage(context.browser, base_url)

    context.browser.visit(base_url)
    header = context.browser.find_by_tag('h1').first.value

    if header == "Log in to PostHog":
        sign_in(context)
    else:
        sign_up(context)
    
    # make sure demo data is populated
    context.browser.visit('http:/localhost:8000/demo')

# behave hook
def after_all(context):
    context.browser.quit()

def sign_up(context):
    context.browser.find_by_id('inputCompany').fill('some company')
    context.browser.find_by_id('inputName').fill('somename')
    context.browser.find_by_id('inputEmail').fill('fakeemail@email.com')
    context.browser.find_by_id('inputPassword').fill('somepassword')
    context.browser.find_by_text('Create account').first.click()

def sign_in(context):
    context.browser.find_by_id('inputEmail').fill('fakeemail@email.com')
    context.browser.find_by_id('inputPassword').fill('somepassword')
    context.browser.find_by_text('Sign in').first.click()