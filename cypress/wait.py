import time

import requests


def main():
    print("Waiting to run tests until PostHog is up and serving requests")
    booted = False
    while not booted:
        try:
            r = requests.get("http://127.0.0.1:8000/_health/")
            if r.status_code == 200:
                booted = True
                print("PostHog is alive! Proceeding")
                continue
            else:
                print("PostHog is still building frontend. Sleeping for 1 second")
        except:
            print("PostHog is still booting. Sleeping for 1 second")
        time.sleep(1)


if __name__ == "__main__":
    main()
