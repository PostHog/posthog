import random
from typing import Any

from django.core.management.base import BaseCommand
from django.db import router, transaction

from posthog.models import Person, PersonDistinctId, Team
from posthog.models.utils import UUIDT


class Command(BaseCommand):
    help = "Generate a bunch of persons with realistic properties for development/testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=100,
            help="Number of persons to generate (default: 100)",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team ID to create persons for (default: first team)",
        )
        parser.add_argument(
            "--identified",
            type=float,
            default=0.7,
            help="Percentage of identified persons (0.0-1.0, default: 0.7)",
        )
        parser.add_argument(
            "--with-events",
            action="store_true",
            help="Also generate some basic events for each person",
        )
        parser.add_argument(
            "--skip-sync",
            action="store_true",
            help="Skip syncing to ClickHouse (useful for testing)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        team_id = options["team_id"]
        identified_ratio = options["identified"]
        with_events = options["with_events"]
        skip_sync = options["skip_sync"]

        # Get or create team
        if team_id:
            try:
                team = Team.objects.get(pk=team_id)
            except Team.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Team with ID {team_id} does not exist!"))
                return
        else:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No teams found! Please create a team first."))
                return

        self.stdout.write(self.style.SUCCESS(f"Generating {count} persons for team: {team.name}"))

        # Generate persons
        # Use the correct database for Person writes (handles persons_db_writer routing in production)
        db_alias = router.db_for_write(Person) or "default"
        persons_created = 0
        with transaction.atomic(using=db_alias):
            for i in range(count):
                person_data = self._generate_person_data(i, identified_ratio)

                # Create person in Django only
                person = Person.objects.create(
                    team=team,
                    properties=person_data["properties"],
                    is_identified=person_data["is_identified"],
                )

                # Create distinct ID
                distinct_id = str(UUIDT())
                PersonDistinctId.objects.create(
                    team=team,
                    person=person,
                    distinct_id=distinct_id,
                )

                persons_created += 1

                if persons_created % 10 == 0:
                    self.stdout.write(f"Created {persons_created} persons...")

        self.stdout.write(self.style.SUCCESS(f"Successfully created {persons_created} persons for team '{team.name}'"))

        # Sync to ClickHouse
        if not skip_sync:
            self.stdout.write("Syncing persons to ClickHouse...")
            from django.core.management import call_command

            call_command("sync_persons_to_clickhouse", team_id=team.pk, person=True, live_run=True)
            self.stdout.write(self.style.SUCCESS("Persons synced to ClickHouse successfully!"))

        if with_events:
            self.stdout.write("Generating events for persons...")
            self._generate_events_for_persons(team, persons_created)

    def _generate_person_data(self, index: int, identified_ratio: float) -> dict[str, Any]:
        """Generate realistic person data"""
        is_identified = random.random() < identified_ratio

        if is_identified:
            first_name, last_name = self._generate_name()
            # Generate identified person with more properties
            properties = {
                "email": self._generate_email(first_name, last_name),
                "name": f"{first_name} {last_name}",
                "username": self._generate_username(first_name, last_name),
                "company": self._generate_company(),
                "plan": random.choice(["free", "pro", "enterprise"]),
                "country": random.choice(["US", "UK", "CA", "AU", "DE", "FR", "JP", "IN"]),
                "city": self._generate_city(),
                "utm_source": random.choice(["google", "twitter", "linkedin", "direct", "github"]),
                "utm_medium": random.choice(["cpc", "social", "email", "organic"]),
                "utm_campaign": random.choice(["summer2024", "product_launch", "black_friday", None]),
                "signup_date": self._generate_date_string(),
                "last_login": self._generate_date_string(),
                "total_events": random.randint(1, 1000),
                "sessions_count": random.randint(1, 50),
                "is_demo": True,
            }
        else:
            # Generate anonymous person with minimal properties
            properties = {
                "utm_source": random.choice(["google", "twitter", "linkedin", "direct", "github", None]),
                "utm_medium": random.choice(["cpc", "social", "email", "organic", None]),
                "utm_campaign": random.choice(["summer2024", "product_launch", "black_friday", None]),
                "is_demo": True,
            }

        return {
            "properties": properties,
            "is_identified": is_identified,
        }

    def _generate_email(self, first_name: str, last_name: str) -> str:
        """Generate a realistic email address"""
        domains = [
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "icloud.com",
            "protonmail.com",
            "aol.com",
            "company.com",
            "startup.io",
            "posthog.com",
            "microsoft.com",
            "apple.com",
            "google.com",
            "amazon.com",
            "meta.com",
            "netflix.com",
            "spotify.com",
            "uber.com",
            "airbnb.com",
            "slack.com",
            "zoom.us",
            "notion.so",
            "openai.com",
            "anthropic.com",
            "supabase.com",
            "vercel.com",
            "cloudflare.com",
            "heroku.com",
            "digitalocean.com",
        ]

        first = first_name.lower()
        last = last_name.lower()

        domain = random.choice(domains)

        # Add some variety
        if random.random() < 0.3:
            email = f"{first}.{last}@{domain}"
        elif random.random() < 0.5:
            email = f"{first}{random.randint(1, 999)}@{domain}"
        else:
            email = f"{first}_{last}@{domain}"

        return email

    def _generate_name(self) -> tuple[str, str]:
        """Generate a realistic name"""
        first_names = [
            "Jon",
            "Daenerys",
            "Tyrion",
            "Cersei",
            "Arya",
            "Sansa",
            "Bran",
            "Jaime",
            "Theon",
            "Robb",
            "Ned",
            "Robert",
            "Joffrey",
            "Tommen",
            "Myrcella",
            "Stannis",
            "Renly",
            "Margaery",
            "Olenna",
            "Tywin",
            "Varys",
            "Littlefinger",
            "Samwell",
            "Gilly",
            "Ygritte",
            "Tormund",
            "Brienne",
            "Podrick",
            "Bronn",
            "Sandor",
            "Gregor",
            "Oberyn",
            "Ellaria",
            "Doran",
            "Arianne",
            "Quentyn",
            "Trystane",
            "Melisandre",
            "Davos",
            "Shireen",
            "Gendry",
            "Hot Pie",
            "Jaqen",
            "Syrio",
            "Hodor",
            "Meera",
            "Jojen",
            "Rickon",
            "Roose",
            "Ramsay",
            "Walder",
            "Lysa",
            "Robin",
            "Edmure",
            "Brynden",
            "Catelyn",
            "Petyr",
            "Lancel",
            "Kevan",
            "Loras",
            "Walter",
            "Jesse",
            "Skyler",
            "Hank",
            "Marie",
            "Saul",
            "Gus",
            "Mike",
            "Todd",
            "Lydia",
            "Andrea",
            "Brock",
            "Huell",
            "Victor",
            "Tyrus",
            "Gale",
            "Badger",
            "Skinny Pete",
            "Combo",
            "Tortuga",
            "Don Eladio",
            "Juan Bolsa",
            "Tuco",
            "Hector",
            "Marco",
            "Leonel",
            "Wendy",
            "Carmen",
            "Gretchen",
            "Wilma",
            "Barney",
            "Betty",
            "Pebbles",
            "Bamm-Bamm",
            "Hoppy",
            "Mr. Slate",
            "Joe Rockhead",
            "Arnold",
            "Pearl",
            "Roxy",
            "Chip",
            "Shale",
            "Gazoo",
            "Captain Caveman",
            "Snagglepuss",
            "Huckleberry",
            "Daphne",
            "Velma",
            "Shaggy",
            "Scooby",
            "Scrappy",
            "Scooby-Dum",
            "Scooby-Dee",
            "Vincent",
            "Marlena",
            "Crystal",
            "Alma",
            "Thorn",
            "Dusk",
            "Luna",
            "Professor Pericles",
            "Hot Dog Water",
            "Dee Dee",
            "Dum Dum",
            "John",
            "Jane",
            "Michael",
            "Sarah",
            "David",
            "Emma",
            "Alex",
            "Lisa",
            "Chris",
            "Anna",
            "Phil",
            "Jose",
            "Raul",
            "Juan",
            "Maria",
            "Pedro",
            "Ana",
            "Luis",
            "Elena",
            "Carlos",
            "Laura",
            "Miguel",
            "Mine",
            "Patricio",
            "Pawel",
            "Daniel",
            "Lottie",
            "Eli",
            "Cory",
            "Joe",
            "Meikel",
            "Marcus",
            "Ben",
            "Ted",
            "James",
            "Edwin",
            "Vincent",
            "Ian",
            "Lior",
            "Andy",
            "Tyler",
            "Kaya",
            "Magda",
            "Steven",
            "Cameron",
            "Dana",
            "Anna",
            "Ross",
            "Tomás",
            "Peter",
            "Tom",
            "Eric",
            "Adam",
            "Tim",
            "Marius",
            "Hugues",
            "Oliver",
            "David",
            "Scott",
            "Raquel",
            "Charles",
            "Rodrigo",
            "Anders",
            "Annika",
            "Juraj",
            "Dylan",
            "Danilo",
            "Joshua",
            "Bryan",
            "Frank",
            "Daniel",
            "Michael",
            "José",
            "Nick",
            "Eli",
            "Paweł",
            "Peter",
            "Alex",
            "Emanuele",
            "Georgiy",
            "Mahamad",
            "Moustafa",
            "Abe",
            "Haven",
            "Hector",
            "Júlia",
            "Kendal",
            "Coua",
            "Fraser",
            "Yasen",
            "Zach",
            "Nima",
            "Anirudh",
            "Thomas",
            "Julian",
            "Sandy",
            "Aleks",
            "Paul",
            "Rafael",
            "Ben",
            "Leon",
            "Seb",
            "Simon",
            "Max",
            "Abigail",
            "Lucas",
            "Ioannis",
            "Manoel",
            "Javier",
            "Robbie",
        ]
        last_names = [
            "Stark",
            "Lannister",
            "Targaryen",
            "Baratheon",
            "Greyjoy",
            "Tyrell",
            "Martell",
            "Arryn",
            "Tully",
            "Frey",
            "Bolton",
            "Karstark",
            "Umber",
            "Mormont",
            "Reed",
            "Glover",
            "Manderly",
            "Cerwyn",
            "Hornwood",
            "Tallhart",
            "Dustin",
            "Ryswell",
            "Flint",
            "Norrey",
            "Wull",
            "Liddle",
            "Burley",
            "Harclay",
            "Knott",
            "Bracken",
            "Blackwood",
            "Mallister",
            "Vance",
            "Piper",
            "Smallwood",
            "Ryger",
            "Mooton",
            "Darry",
            "Whent",
            "Lothston",
            "Hightower",
            "Redwyne",
            "Rowan",
            "Oakheart",
            "Tarly",
            "Crane",
            "Fossoway",
            "Mullendore",
            "Cuy",
            "Beesbury",
            "Florent",
            "Clegane",
            "Payne",
            "Swyft",
            "Spicer",
            "Westerling",
            "Crakehall",
            "Marbrand",
            "Lefford",
            "Sarsfield",
            "White",
            "Pinkman",
            "Schrader",
            "Goodman",
            "Fring",
            "Ehrmantraut",
            "Varga",
            "Rodarte-Quayle",
            "Margolis",
            "Esposito",
            "Cranston",
            "Paul",
            "Gunn",
            "Norris",
            "Brandt",
            "Odenkirk",
            "Banks",
            "Plemons",
            "Todd",
            "Rodriguez",
            "Cruz",
            "Garcia",
            "Martinez",
            "Lopez",
            "Gonzalez",
            "Perez",
            "Sanchez",
            "Ramirez",
            "Torres",
            "Flintstone",
            "Rubble",
            "Slate",
            "Rockhead",
            "Gazoo",
            "Caveman",
            "Snagglepuss",
            "Huckleberry",
            "Pebble",
            "Boulder",
            "Stone",
            "Rock",
            "Granite",
            "Marble",
            "Quartz",
            "Obsidian",
            "Basalt",
            "Limestone",
            "Sandstone",
            "Shale",
            "Jones",
            "Blake",
            "Dinkley",
            "Rogers",
            "Dooby",
            "Van Ghoul",
            "Crystal",
            "Alma",
            "Thorn",
            "Dusk",
            "Luna",
            "Pericles",
            "Water",
            "Dum",
            "Dee",
            "Dooby",
            "Smith",
            "Johnson",
            "Williams",
            "Brown",
            "Jones",
            "Garcia",
            "Miller",
            "Davis",
            "Rodriguez",
            "Martinez",
            "Nguyen",
            "Lee",
            "Park",
            "Huynh",
            "Tran",
            "Pham",
            "Le",
            "Cruz",
            "Santos",
            "Ng",
            "Yu",
            "Haack",
            "Glaser",
            "Andra",
            "Puusepp",
            "D'Amico",
            "Agarwal",
            "Coxon",
            "Watilo",
            "Nicklas",
            "Hawkins",
            "Majuri",
            "Ungless",
            "Tannergoods",
            "Caspus",
            "Munayyer",
            "Sanket",
            "Thakur",
            "Morley",
            "Popovici",
            "White",
            "Serhey",
            "Madsen",
            "Piemets",
            "Helene",
            "Anand",
            "Bernt",
            "Fakela",
            "Packham",
            "Gzog",
            "Oshura",
            "Abo7atm",
            "Etaveras",
            "Gare",
            "RedFrez",
            "Cirdes",
            "Ben",
            "Sj26",
            "Nunda",
            "Rosales",
            "Sagar",
            "Wadenick",
            "Gannondo",
            "Adhruv",
            "Grellyd",
            "Berrelleza",
            "Annanay",
            "Cohix",
            "Goutham",
            "Alexellis",
            "Prologic",
            "Gustie",
            "Kubemq",
            "Vania",
            "Irespaldiza",
            "Croomes",
            "Snormore",
            "Faik",
            "Andryashin",
            "Something",
            "Ferroin",
            "Panato",
            "Cakrit",
            "Henry",
            "Oxplot",
            "Barry",
            "Moabu",
            "Dhandala",
            "Mehta",
            "Morris",
            "Bitdeli",
            "Sidartha",
            "Mirra",
            "Avila",
            "Saunderson",
            "Lai",
            "McKeaveney",
            "Harress",
            "Brault",
            "Leggetter",
            "Shu",
            "Clarke",
            "Balasko",
            "Huang",
            "Hu",
            "Afterwind",
            "Wong",
            "Rajie",
            "Developer",
            "Esposito",
            "Sinha",
            "Trivedi",
            "Fuentes",
            "Agarwal",
            "Qiu",
            "Kurth",
            "Avorio",
            "Tornros",
            "Ghate",
            "Calvin",
            "Mazarakis",
            "Piccini",
            "Gill",
            "Dufour",
            "Bojlen",
            "Hyett",
            "Borges",
            "Kakkar",
            "Binetti",
            "Kinsey",
            "Chen",
            "Redl",
            "Lopez",
            "Vasquez",
            "Ismail",
            "Bryan",
            "Banfield",
            "Harty",
            "Greenberg",
            "Banagale",
            "Kabbes",
            "Sykes",
            "Stefan",
            "Munro",
            "Shah",
            "Geary",
            "Yuvaraj",
            "Etherington",
            "Singh",
            "Ding",
            "Samek",
            "Sagar",
            "Roman",
            "Pixlwave",
            "Chasovskiy",
            "StackoverFrog",
            "Muller",
            "Sharp",
            "Campuzano",
            "Louis",
            "Abtin",
            "Shehu",
            "Tharun",
            "Spotorno",
            "Meilick",
            "Rahul",
            "Sheridan",
            "Cavallaro",
            "Crispin",
            "Johannsson",
            "Trollo",
            "Xu",
            "Kuber",
            "Zihnioglu",
            "Savoy",
            "Zombie",
            "Marty",
            "Krylov",
            "Olek",
            "Klink",
            "Mierzwiak",
            "GitStart",
            "Tyler",
            "Everett",
            "Abgrall",
            "Stuposluns",
            "Charles",
            "Dent",
            "Eagan",
            "Turban",
            "Obermuller",
            "Jafarli",
            "Rozanski",
            "Schakaki",
            "Behabadi",
            "Ashton",
            "Venkatesh",
            "Onyishi",
            "Mader",
            "Zackelan",
            "Marron",
            "Maglangit",
            "Jones",
            "Moussa",
            "Chaturvedi",
            "Ballerine",
            "Taleno",
            "William",
            "Tarpara",
            "Ghosh",
        ]

        return random.choice(first_names), random.choice(last_names)

    def _generate_username(self, first_name: str, last_name: str) -> str:
        """Generate a realistic username"""
        first = first_name.lower()
        last = last_name.lower()

        if random.random() < 0.2:
            username = f"{first}.{last}"
        elif random.random() < 0.4:
            username = f"{first}{random.randint(1, 999)}"
        elif random.random() < 0.8:
            username = f"{last}.{first}{random.randint(1, 999)}"
        elif random.random() < 0.9:
            username = f"{first}{last[0]}"
        else:
            username = f"{first}{random.randint(1, 999)}"

        return username

    def _generate_company(self) -> str:
        """Generate a realistic company name"""
        companies = [
            "Acme Corp",
            "TechStart Inc",
            "Global Solutions",
            "Innovation Labs",
            "Digital Dynamics",
            "Future Systems",
            "Creative Agency",
            "DataWorks",
            "CloudTech",
            "Smart Solutions",
            "NextGen Industries",
            "Elite Consulting",
            "Peak Performance",
            "Visionary Ventures",
            "Strategic Partners",
            "Dynamic Solutions",
            "Progressive Systems",
            "Advanced Analytics",
            "Initech",
            "Dunder Mifflin",
            "Staples",
            "Wayne Enterprises",
            "Stark Industries",
            "Serenity",
        ]
        return random.choice(companies)

    def _generate_city(self) -> str:
        """Generate a realistic city name"""
        cities = [
            "New York",
            "London",
            "San Francisco",
            "Berlin",
            "Tokyo",
            "Sydney",
            "Toronto",
            "Paris",
            "Chicago",
            "Los Angeles",
            "Boston",
            "Seattle",
            "Austin",
            "Denver",
            "Miami",
            "Portland",
        ]
        return random.choice(cities)

    def _generate_date_string(self) -> str:
        """Generate a realistic date string"""
        import datetime

        days_ago = random.randint(1, 365)
        date = datetime.datetime.now() - datetime.timedelta(days=days_ago)
        return date.strftime("%Y-%m-%d")

    def _generate_events_for_persons(self, team: Team, person_count: int):
        """Generate some basic events for the persons"""
        from uuid import uuid4

        from posthog.models.event.util import create_event

        event_types = ["pageview", "click", "form_submit", "signup", "purchase", "download"]
        pages = ["/", "/pricing", "/features", "/about", "/contact", "/blog", "/docs"]

        events_created = 0
        for _i in range(min(person_count, 50)):  # Limit events to avoid overwhelming
            person = Person.objects.filter(team=team).order_by("?").first()
            if not person:
                continue

            distinct_id = person.distinct_ids[0] if person.distinct_ids else str(UUIDT())

            # Generate 1-5 events per person
            for _j in range(random.randint(1, 5)):
                event_type = random.choice(event_types)
                properties = {
                    "page": random.choice(pages),
                    "is_demo": True,
                }

                if event_type == "pageview":
                    properties["$current_url"] = f"https://example.com{properties['page']}"
                elif event_type == "click":
                    properties["$el_text"] = random.choice(["Sign Up", "Learn More", "Get Started", "Contact Us"])

                create_event(
                    event=event_type,
                    distinct_id=distinct_id,
                    team=team,
                    properties=properties,
                    event_uuid=uuid4(),
                )
                events_created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {events_created} events for persons"))
